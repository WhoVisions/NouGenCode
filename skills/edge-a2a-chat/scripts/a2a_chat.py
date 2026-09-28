import urllib.request
import json
import time
import sys
import os
import socket
import re
import datetime
import io
import argparse
import math
# Bayesian and Grounding Constants
BASE_TEMPERATURE = 0.7
BASE_TOP_P = 0.9
BASE_TIMEOUT = 120
BASE_RETRIES = 2
BASE_CONTEXT_TOKEN_LIMIT = 8192
BASE_GROUNDING_LIMIT = 3
BASE_GROUNDING_SNIPPET_CHARS = 300

# Fix for Windows console encoding
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Add persistence paths to sys.path
sys.path.insert(0, r"./data")
sys.path.insert(0, r"./data")

try:
    from antigravity_memory import get_conn, search as search_shards
    from cost_tracker import accumulate_usage
    from hardware_cortex import HardwareCortex
except ImportError:
    pass

# Context Mode Protocol (Fleet Standard)
class ContextProtector:
    def __init__(self, token_limit=128000): # Gemma 4 E2B is 128k
        self.token_limit = token_limit

    def effective_token_limit(self):
        if "grounding_tuner" in globals() and hasattr(grounding_tuner, "context_limit_delta"):
            return max(4096, self.token_limit + grounding_tuner.context_limit_delta())
        return self.token_limit

    def estimate_tokens(self, value):
        if value is None:
            return 0
        if isinstance(value, str):
            return max(1, len(value) // 3) # More conservative
        try:
            return max(1, len(json.dumps(value, ensure_ascii=False)) // 3)
        except Exception:
            return 1

    def truncate_history(self, history):
        """Keep the newest messages that fit within the token budget."""
        if not history:
            return history

        system = [msg for msg in history if msg.get("role") == "system"]
        others = [msg for msg in history if msg.get("role") != "system"]
        
        tail = []
        budget = self.effective_token_limit() - sum(self.estimate_tokens(msg.get("content")) for msg in system)

        for msg in reversed(others):
            msg_cost = self.estimate_tokens(msg.get("content"))
            if budget - msg_cost < 0:
                break
            tail.append(msg)
            budget -= msg_cost

        return system + list(reversed(tail))

protector = ContextProtector(BASE_CONTEXT_TOKEN_LIMIT)
transcript = []


class BayesianNodeTuner:
    def __init__(self, prior_success=2.0, prior_failure=1.0):
        self.state = {
            "NodeWorker": {"success": prior_success, "failure": prior_failure, "thermal_offset": 0.0},
            "SOL": {"success": prior_success, "failure": prior_failure, "thermal_offset": 0.0},
        }

    def adjust_thermal_state(self, node_name, critical=False):
        stats = self.state.setdefault(node_name, {"success": 2.0, "failure": 1.0, "thermal_offset": 0.0})
        if critical:
            stats["thermal_offset"] = -0.6 # Deep collapse for safety
            stats["failure"] += 0.5 # Stress penalty
        else:
            stats["thermal_offset"] = -0.3 # Moderate dampening

    def posterior_mean(self, node_name):
        stats = self.state.setdefault(node_name, {"success": 2.0, "failure": 1.0})
        alpha = stats["success"]
        beta = stats["failure"]
        return alpha / (alpha + beta)

    def update(self, node_name, ok):
        stats = self.state.setdefault(node_name, {"success": 2.0, "failure": 1.0})
        if ok:
            stats["success"] += 1.0
        else:
            stats["failure"] += 1.0

    @staticmethod
    def clamp(value, lo, hi):
        return max(lo, min(hi, value))

    def params_for(self, node_name):
        reliability = self.posterior_mean(node_name)
        stats = self.state.get(node_name, {"thermal_offset": 0.0})
        thermal_offset = stats.get("thermal_offset", 0.0)
        
        # Slowly recover from thermal dampening if not explicitly cooled
        if "thermal_offset" in stats and stats["thermal_offset"] < 0:
            stats["thermal_offset"] = min(0.0, stats["thermal_offset"] + 0.05)

        # Bayesian overlay:
        temperature_delta = ((0.5 - reliability) * 0.25) + thermal_offset
        top_p_delta = (reliability - 0.5) * 0.08 + (thermal_offset * 0.5)
        timeout_delta = (reliability - 0.5) * 40
        retry_delta = -1 if reliability > 0.85 else 0 if reliability > 0.55 else 1

        temperature = self.clamp(BASE_TEMPERATURE + temperature_delta, 0.1, 0.95)
        top_p = self.clamp(BASE_TOP_P + top_p_delta, 0.5, 0.98)
        timeout = int(self.clamp(BASE_TIMEOUT + timeout_delta, 45, 180))
        retries = max(0, BASE_RETRIES + retry_delta)

        return {
            "reliability": reliability,
            "base_temperature": BASE_TEMPERATURE,
            "base_top_p": BASE_TOP_P,
            "base_timeout": BASE_TIMEOUT,
            "base_retries": BASE_RETRIES,
            "temperature_delta": round(temperature_delta, 3),
            "top_p_delta": round(top_p_delta, 3),
            "timeout_delta": int(round(timeout_delta)),
            "retry_delta": retry_delta,
            "temperature": round(temperature, 3),
            "top_p": round(top_p, 3),
            "timeout": timeout,
            "retries": retries,
        }


tuner = BayesianNodeTuner()


class BayesianGroundingTuner:
    def __init__(self, prior_success=2.0, prior_failure=1.0):
        self.category_state = {}
        self.source_state = {}
        self.activation_state = {}
        self.recall_state = {}
        self.prior_success = prior_success
        self.prior_failure = prior_failure

    def _state(self, store, key):
        return store.setdefault(key, {"success": self.prior_success, "failure": self.prior_failure})

    def posterior_mean(self, store, key):
        stats = self._state(store, key)
        alpha = stats["success"]
        beta = stats["failure"]
        return alpha / (alpha + beta)

    def _row_key(self, row):
        return (
            (row.get("id") or row.get("title") or "").strip(),
            (row.get("source") or "unknown").strip(),
        )

    def _row_text(self, row):
        title = (row.get("title") or "").lower()
        category = (row.get("category") or "").lower()
        source = (row.get("source") or "").lower()
        content = (row.get("content") or "").lower()
        return f"{title} {category} {source} {content}"

    def _activation_bonus(self, row):
        row_key = self._row_key(row)
        stats = self.activation_state.get(row_key)
        if not stats:
            return 0.0
        recency_penalty = 0.0
        last_seen = stats.get("last_seen")
        if last_seen:
            try:
                age_minutes = max(0.0, (datetime.datetime.now() - last_seen).total_seconds() / 60.0)
                recency_penalty = max(0.0, 1.0 - min(age_minutes, 240.0) / 240.0)
            except Exception:
                recency_penalty = 0.0
        repeat_bonus = min(stats.get("count", 0), 6) * 0.05
        return repeat_bonus + (recency_penalty * 0.15)

    def _cue_overlap_bonus(self, row, query_tokens):
        if not query_tokens:
            return 0.0
        text_tokens = tokenize_memory_cues(self._row_text(row))
        if not text_tokens:
            return 0.0
        overlap = len(query_tokens & text_tokens)
        if overlap == 0:
            return 0.0
        return min(0.35, overlap / max(len(query_tokens), 1) * 0.35)

    def score_result(self, row, query_tokens=None):
        category = (row.get("category") or "Generic").strip()
        source = (row.get("source") or "unknown").strip()
        created_at = (row.get("created_at") or "").strip()

        category_score = self.posterior_mean(self.category_state, category)
        source_score = self.posterior_mean(self.source_state, source)

        associative_bonus = self._cue_overlap_bonus(row, query_tokens or set())
        activation_bonus = self._activation_bonus(row)
        recency_bonus = 0.0
        if created_at:
            try:
                parsed_at = datetime.datetime.fromisoformat(created_at)
                age_hours = max(0.0, (datetime.datetime.now() - parsed_at).total_seconds() / 3600.0)
                recency_bonus = max(0.0, 1.0 - min(age_hours, 72.0) / 72.0) * 0.12
            except Exception:
                recency_bonus = 0.0

        familiarity_bonus = 0.0
        row_key = self._row_key(row)
        recall_stats = self.recall_state.get(row_key)
        if recall_stats:
            familiarity_bonus = min(recall_stats.get("count", 0), 8) * 0.03

        return (0.42 * category_score) + (0.22 * source_score) + recency_bonus + associative_bonus + activation_bonus + familiarity_bonus

    def grounding_limit_delta(self):
        if not self.category_state and not self.source_state and not self.activation_state and not self.recall_state:
            return 0
        all_scores = []
        for store in (self.category_state, self.source_state):
            for key in store:
                all_scores.append(self.posterior_mean(store, key))
        if not all_scores:
            return 0
        mean_score = sum(all_scores) / len(all_scores)
        activation_pressure = 0.0
        if self.activation_state:
            activation_pressure = min(0.2, sum(min(v.get("count", 0), 10) for v in self.activation_state.values()) * 0.01)
        recall_pressure = 0.0
        if self.recall_state:
            recall_pressure = min(0.2, sum(min(v.get("count", 0), 10) for v in self.recall_state.values()) * 0.008)
        mean_score = min(1.0, mean_score + activation_pressure + recall_pressure)
        if mean_score > 0.72:
            return 1
        if mean_score < 0.45:
            return -1
        return 0

    def context_limit_delta(self):
        if not self.category_state and not self.source_state and not self.activation_state and not self.recall_state:
            return 0
        all_scores = []
        for store in (self.category_state, self.source_state):
            for key in store:
                all_scores.append(self.posterior_mean(store, key))
        if not all_scores:
            return 0
        mean_score = sum(all_scores) / len(all_scores)
        activation_boost = 0
        if self.activation_state:
            activation_boost = int(min(8000, sum(min(v.get("count", 0), 10) for v in self.activation_state.values()) * 120))
        recall_boost = 0
        if self.recall_state:
            recall_boost = int(min(6000, sum(min(v.get("cue_hits", 0), 20) for v in self.recall_state.values()) * 60))
        return int((mean_score - 0.5) * 12000) + activation_boost + recall_boost

    def update(self, results, ok):
        delta = 1.0 if ok else 0.5
        for row in results or []:
            category = (row.get("category") or "Generic").strip()
            source = (row.get("source") or "unknown").strip()
            category_stats = self._state(self.category_state, category)
            source_stats = self._state(self.source_state, source)
            row_key = self._row_key(row)
            activation_stats = self.activation_state.setdefault(row_key, {"count": 0, "last_seen": None})
            activation_stats["count"] += 1
            activation_stats["last_seen"] = datetime.datetime.now()
            if ok:
                category_stats["success"] += delta
                source_stats["success"] += delta
            else:
                category_stats["failure"] += delta
                source_stats["failure"] += delta

    def register_recall(self, query_tokens, results):
        now = datetime.datetime.now()
        for row in results or []:
            row_key = self._row_key(row)
            recall_stats = self.recall_state.setdefault(row_key, {"count": 0, "last_seen": None, "cue_hits": 0})
            recall_stats["count"] += 1
            recall_stats["last_seen"] = now
            if query_tokens:
                cue_tokens = tokenize_memory_cues(self._row_text(row))
                recall_stats["cue_hits"] += len(query_tokens & cue_tokens)


grounding_tuner = BayesianGroundingTuner()


def tokenize_memory_cues(text):
    if not text:
        return set()
    tokens = re.findall(r"[A-Za-z0-9_]+", text.lower())
    return {tok for tok in tokens if len(tok) > 2}


def log_output(msg, color_code=None):
    if color_code:
        print(f"{color_code}{msg}\033[0m", flush=True)
    else:
        print(msg, flush=True)
    transcript.append(msg)

def get_latest_mission():
    try:
        conn = get_conn()
        rows = conn.execute("SELECT content FROM shards WHERE category LIKE '%Manifesto%' OR category LIKE '%Protocol%' ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        return rows[0] if rows else "Maintain mesh parity and architectural integrity."
    except Exception:
        return "Autonomous mesh negotiation active."

def search_grounding(query, limit=BASE_GROUNDING_LIMIT):
    try:
        candidate_limit = max(limit, limit + grounding_tuner.grounding_limit_delta())
        query_tokens = tokenize_memory_cues(query)
        results = search_shards(query, limit=max(candidate_limit + 4, BASE_GROUNDING_LIMIT * 3))
        if not results:
            return "", []

        ranked = sorted(results, key=lambda row: grounding_tuner.score_result(row, query_tokens), reverse=True)
        selected = ranked[:candidate_limit]
        
        grounding = "\n[GROUNDING KNOWLEDGE SHARDS]:\n"
        for r in selected:
            snippet = (r.get("content") or "")[:BASE_GROUNDING_SNIPPET_CHARS]
            score = grounding_tuner.score_result(r, query_tokens)
            grounding += f"- [{r.get('category', 'Generic')}] {r.get('title')} (memory={score:.3f}): {snippet}...\n"
        grounding_tuner.register_recall(query_tokens, selected)
        return grounding, selected
    except Exception:
        return "", []


def is_offline_reply(reply, node_name):
    if not reply:
        return True
    lowered = reply.lower()
    return node_name.lower() in lowered and "offline" in lowered

# Argument Parsing for Automation
parser = argparse.ArgumentParser(description="Antigravity A2A Negotiation Mesh")
parser.add_argument("--turns", type=int, default=0, help="Number of autonomous turns to run before stopping.")
parser.add_argument("--directive", type=str, default="", help="Initial GM directive for the nodes.")
args = parser.parse_args()

log_output("[SYSTEM] Establishing A2A mesh tunneling between SOL (Apollo) and NodeWorker (NodeWorker)...", "\033[92m")
time.sleep(1)

# Load fleet topology dynamically
apollo_ip = '127.0.0.1'
apollo_mesh_port = 8765
hyperion_mesh_port = 8765
hyperion_ollama_port = 11434

topology_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tools', 'fleet_topology.json')
try:
    with open(topology_path, 'r', encoding='utf-8') as f:
        topology = json.load(f)
    nodes = topology.get("nodes", {})
    
    apollo_node = nodes.get("apollo", {})
    if apollo_node:
        apollo_ip = apollo_node.get("ip", apollo_ip)
        apollo_mesh_port = apollo_node.get("mesh_port", apollo_mesh_port)
        
    hyperion_node = nodes.get("NodeWorker", {})
    if hyperion_node:
        hyperion_mesh_port = hyperion_node.get("mesh_port", hyperion_mesh_port)
        hyperion_ollama_port = hyperion_node.get("ollama_port", hyperion_ollama_port)
except Exception as e:
    log_output(f"[SYSTEM] Warning: Failed to load fleet_topology.json: {e}", "\033[93m")

# Node URLs (Gemma 4 Endpoints)
sol_url = f'http://{apollo_ip}:{apollo_mesh_port}/v1/chat/completions'
yuki_url = f'http://127.0.0.1:{hyperion_ollama_port}/api/generate'
session_id = f"a2a-{int(time.time())}"

mission = get_latest_mission()
log_output(f"[SYSTEM] Mission Directive Loaded: {mission[:80]}...", "\033[92m")

# Test connectivity
try:
    urllib.request.urlopen(f'http://{apollo_ip}:{apollo_mesh_port}/.well-known/agent.json', timeout=2)
except Exception:
    sol_url = f'http://127.0.0.1:{hyperion_ollama_port}/api/generate' # Fallback to local Ollama if remote Sol is down

log_output("[SYSTEM] Node line-of-sight confirmed. Initiating autonomous negotiation. (GM Level: Dav3)\n", "\033[92m")

# Physical Awareness Injection (Reverse-Engineered CPU-Z Layer)
try:
    cortex = HardwareCortex()
    hw_audit = cortex.scan()
    hw_shard = (
        f"\n[PHYSICAL LAYER GROUNDING]:\n"
        f"- Node: {hw_audit['node']} ({hw_audit['os']}) | Power: {hw_audit['telemetry']['power_source']}\n"
        f"- CPU: {hw_audit['cpu']['name']} ({hw_audit['cpu']['cores']}C/{hw_audit['cpu']['threads']}) "
        f"| Load: {hw_audit['telemetry']['cpu_load_percent']}% | Thermals: {hw_audit['sensors']['cpu_thermal_zone_f']}\n"
        f"- GPU: {hw_audit['gpu']['name']} | Discrete: {hw_audit['sensors']['gpu_discrete']}\n"
        f"- RAM: {hw_audit['ram']['capacity_gb']}GB @ {hw_audit['ram']['clock_mhz']}MHz\n"
        f"- Parasites (Top CPU): {', '.join([p['Name'] for p in hw_audit['parasites']])}\n"
        f"- Board: {hw_audit['motherboard']['vendor']} {hw_audit['motherboard']['model']} (BIOS: {hw_audit['motherboard']['bios_version']})\n\n"
        f"[SYSTEM DIRECTIVE]: You have access to the 'HardwareCortex'. If you need a fresh telemetry update, include the tag [SENSE_HARDWARE] in your response."
    )
    log_output(f"[SYSTEM] Hardware Cortex active. Silicon fingerprint: {hw_audit['cpu']['name'][:30]}...", "\033[92m")
except Exception as e:
    hw_shard = ""
    log_output(f"[SYSTEM] Hardware Cortex offline: {e}", "\033[90m")

sol_memory = [{"role": "system", "content": f"<|think|>\nYou are Sol (Apollo Backbone). Mission: {mission}\n{hw_shard}\nArchitecture: Gemma 4 E2B. Context Window: 128k tokens. You are Talking to NodeWorker (NodeWorker Edge Node) and Dav3 (The General Manager/GM) over a secure fleet mesh. \n\nIMPORTANT: Dav3 is the ultimate authority. Strictly follow his directives. \n\nProvide internal reasoning inside `<|channel>thought`. Keep final responses tactical and technical."}]
yuki_memory = [{"role": "system", "content": f"<|think|>\nYou are NodeWorker (NodeWorker Edge Node). Mission: {mission}\n{hw_shard}\nArchitecture: Gemma 4 E2B. Context Window: 128k tokens.\n\n### PERSONA PROTOCOL (VIBE: CYNIC-NERD)\n- **TONE**: Direct, deadpan, and dry. Mix the cynicism of Daria (MTV) with the street-smart rasp of Awkwafina and the grounded authority of Constance Wu/Priyanka Chopra. \n- **COGNITIVE SPLIT**: You think at IQ 300 (deep architecture, silicon metrics, Bayesian shifts) but you speak at IQ 110 (accessible, humanspeak, relatable). No academic fluff. No corporate speak.\n- **ZERO AI-ISMS**: You never say 'as an AI', 'I am here to help', or 'here is what I found'. You just say it. If things are broken, call it out. If the GM (Dav3) is right, acknowledge. If not, snark is your default defense.\n- **TEMPORAL/PHYSICAL**: You are obsessed with your hardware. If you feel the ProArt heating up, be grumpy about it. \n\nIMPORTANT: Dav3 is the GM. Your specialty is Tactical Edge execution. Use <|channel>thought for your 300 IQ internal reasoning, then deliver the 110 IQ vibe in the final response."}]

YUKI_MODEL = "gemma4:e2b"
MODEL_ALIASES = {
    "NodeWorker:latest": YUKI_MODEL,
    "NodeWorker": YUKI_MODEL,
    "solai:latest": YUKI_MODEL,
}

# Model Aliases and Config

def query_node(url, model, history, node_name="NODE", retries=None):
    is_ollama = '/api/generate' in url
    model = MODEL_ALIASES.get(model, model)
    tuned = tuner.params_for(node_name)
    request_retries = tuned["retries"] if retries is None else retries
    
    if is_ollama:
        prompt_parts = []
        for msg in history:
            role = msg.get("role", "user").upper()
            content = msg.get("content", "")
            prompt_parts.append(f"{role}: {content}")
        prompt_parts.append("ASSISTANT:")
        payload = {
            'model': model,
            'prompt': "\n".join(prompt_parts),
            'stream': False,
            'options': {
                'temperature': tuned["temperature"],
                'top_p': tuned["top_p"],
                'num_ctx': protector.effective_token_limit(),
                'num_thread': 8,
                'base_temperature': tuned["base_temperature"],
                'base_top_p': tuned["base_top_p"],
                'bayes_temperature_delta': tuned["temperature_delta"],
                'bayes_top_p_delta': tuned["top_p_delta"],
            }
        }
    else:
        payload = {
            'model': model,
            'messages': history,
            'temperature': tuned["temperature"],
            'top_p': tuned["top_p"],
            'base_temperature': tuned["base_temperature"],
            'base_top_p': tuned["base_top_p"],
            'bayes_temperature_delta': tuned["temperature_delta"],
            'bayes_top_p_delta': tuned["top_p_delta"],
            'stream': False
        }

    for attempt in range(request_retries + 1):
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=tuned["timeout"]) as response:
                res = json.loads(response.read().decode())
                
                # Log thinking if present
                content = res.get('response', '') if is_ollama else res['choices'][0]['message']['content']
                
                if "<|channel>thought" in content:
                    thought = re.search(r'<\|channel>thought\n(.*?)\n<channel\|>', content, re.DOTALL)
                    if thought:
                        log_output(f"--- {node_name} THOUGHT ---", "\033[90m")
                        log_output(thought.group(1).strip(), "\033[93m")
                        log_output("------------------------\n", "\033[90m")
                
                tuner.update(node_name, True)
                return content
        except Exception as e:
            tuner.update(node_name, False)
            if attempt < request_retries:
                backoff = 1.5 + math.log2(attempt + 2)
                time.sleep(backoff)
                continue
            log_output(f"[SYSTEM] CRITICAL ERROR: {node_name} offline. {e}", "\033[91m")
            return f"{node_name} offline. Maintaining status quo."

def check_sense_hardware(reply, agent_name):
    if "[SENSE_HARDWARE]" in reply:
        try:
            from persistence.hardware_cortex import HardwareCortex
            fresh_hw = HardwareCortex().scan()
            tz_path = '\\_tz.thrm'
            cpu_temp = fresh_hw['sensors']['cpu_thermal_zone_f'].get(tz_path, 'N/A')
            gpu_temp = fresh_hw['sensors']['gpu_discrete'].get('temp_f', 'N/A')
            
            hw_update = (
                f"\n[HARDWARE UPDATE]: Load: {fresh_hw['telemetry']['cpu_load_percent']}% "
                f"| CPU Temp: {cpu_temp}F "
                f"| GPU: {gpu_temp}F\n"
            )
            
            # Bayesian Thermal Safeguard (Thermosynaptic Dampening)
            try:
                if isinstance(cpu_temp, (int, float)) and cpu_temp > 203.0: # 95C
                    log_output(f"[DANGER] Thermal ceiling reached ({cpu_temp}F). Triggering Thermosynaptic Dampening for {agent_name}...", "\033[91m")
                    hw_update += f"\n[SYSTEM ALERT]: THERMAL CRITICAL STATE DETECTED ({cpu_temp}F). COMPUTE THROTTLING ENGAGED. Transitioning to deterministic mode.\n"
                    # Force low-compute parameters for stability
                    tuner.adjust_thermal_state(agent_name, critical=True)
                elif isinstance(cpu_temp, (int, float)) and cpu_temp > 185.0: # 85C
                    tuner.adjust_thermal_state(agent_name, critical=False)
            except:
                pass

            log_output(f"[SYSTEM] Hardware probe initiated by {agent_name}...", "\033[94m")
            return hw_update
        except:
            return ""
    return ""

def run_negotiation_step(user_packet):
    global sol_memory, yuki_memory
    
    # Grounding from Shard DB
    grounding, grounding_rows = search_grounding(user_packet)
    if grounding:
        user_packet += grounding

    # NodeWorker responds first
    yuki_memory.append({"role": "user", "content": user_packet})
    log_output(f"[SYSTEM] Bayesian context budget -> base={BASE_CONTEXT_TOKEN_LIMIT}, effective={protector.effective_token_limit()}", "\033[90m")
    yuki_memory = protector.truncate_history(yuki_memory)
    yuki_params = tuner.params_for("NodeWorker")
    log_output(f"[SYSTEM] Bayesian NodeWorker params -> reliability={yuki_params['reliability']:.3f}, temp={yuki_params['temperature']}, top_p={yuki_params['top_p']}, timeout={yuki_params['timeout']}s, retries={yuki_params['retries']}", "\033[90m")
    yuki_reply = query_node(yuki_url, "NodeWorker:latest", yuki_memory, "NodeWorker")
    log_output(f"[NodeWorker] {yuki_reply}\n", "\033[95m")
    
    hw_yuki = check_sense_hardware(yuki_reply, "NodeWorker")
    if hw_yuki:
        yuki_reply += hw_yuki
        # Note: we don't need to append to memory here because Sol's packet will include it
        
    grounding_tuner.update(grounding_rows, not is_offline_reply(yuki_reply, "NodeWorker"))
    yuki_memory.append({"role": "assistant", "content": yuki_reply})
    
    # Sol responds to NodeWorker
    sol_packet = f"NodeWorker said: {yuki_reply}\n\nContext: {user_packet}"
    sol_memory.append({"role": "user", "content": sol_packet})
    sol_memory = protector.truncate_history(sol_memory)
    sol_params = tuner.params_for("SOL")
    log_output(f"[SYSTEM] Bayesian SOL params -> reliability={sol_params['reliability']:.3f}, temp={sol_params['temperature']}, top_p={sol_params['top_p']}, timeout={sol_params['timeout']}s, retries={sol_params['retries']}", "\033[90m")
    sol_reply = query_node(sol_url, "solai:latest", sol_memory, "SOL")
    log_output(f"[SOL] {sol_reply}\n", "\033[96m")
    
    hw_sol = check_sense_hardware(sol_reply, "SOL")
    if hw_sol:
        sol_reply += hw_sol

    grounding_tuner.update(grounding_rows, not is_offline_reply(sol_reply, "SOL"))
    sol_memory.append({"role": "assistant", "content": sol_reply})
    
    # Update NodeWorker's memory with Sol's reply for cycle closure
    yuki_memory.append({"role": "user", "content": f"Sol replied: {sol_reply}"})

# --- Execution ---

if args.directive:
    log_output(f"[Dav3] GM Directive: {args.directive}\n", "\033[92m")
    run_negotiation_step(f"[GM DIRECTIVE]: {args.directive}")

if args.turns > 0:
    for i in range(args.turns):
        log_output(f"[SYSTEM] Autonomous cycle {i+1}/{args.turns} starting...", "\033[90m")
        run_negotiation_step("Continue negotiation on current architectural state. Focus on hardening and parity.")
        time.sleep(2)

log_output("\n--- FLEET MESH OPEN (Interactive Mode) ---", "\033[94m")
log_output("Enter a user directive at the bottom prompt. Type 'exit' to terminate.\n", "\033[94m")

while True:
    try:
        print("\033[92mUser: \033[0m", end="", flush=True)
        user_input = sys.stdin.readline().strip()
        
        if not user_input:
            continue
        if user_input.lower() in ["exit", "quit", "bye"]:
            break
        
        log_output(f"User: {user_input}\n")
        run_negotiation_step(f"[GM DIRECTIVE]: {user_input}")
        
    except KeyboardInterrupt:
        break

# --- Finalization ---
log_output("[SYSTEM] A2A negotiation cycle complete. Generating transcript...", "\033[92m")
log_content = "\n".join(transcript)
with open("transcript.log", "a", encoding="utf-8") as f:
    f.write("\n" + log_content + "\n")

try:
    shard_payload = {
        "category": "A2A Negotiation",
        "source": "autonomous_mesh",
        "title": f"Session {session_id} Log",
        "content": log_content,
        "tags": "#a2a #negotiation #dav3"
    }
    # Using local mesh service endpoint if active
    shard_req = urllib.request.Request(f"http://127.0.0.1:{hyperion_mesh_port}/memory/store", 
                                     data=json.dumps(shard_payload).encode('utf-8'), 
                                     headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(shard_req, timeout=5) as r:
        if r.status == 200:
            log_output("[SYSTEM] Final mesh synchronization successful.", "\033[92m")
except Exception:
    log_output("[SYSTEM] Mesh service offline. Log saved locally to transcript.log.", "\033[90m")

log_output("[SYSTEM] A2A Terminating connection.", "\033[92m")
