"""
NodeWorker Reasoning Engine - Correct Minimal Implementation
Following Vertex AI Reasoning Engine requirements exactly.
"""




# Deployment script
if __name__ == "__main__":
    import vertexai
    from vertexai.preview import reasoning_engines
    
    PROJECT = os.environ.get("PROJECT_ID", "default-project")
    LOCATION = "us-central1"
    BUCKET = "gs://gen-lang-client-0939852539-NodeWorker-staging"
    
    vertexai.init(project=PROJECT, location=LOCATION, staging_bucket=BUCKET)
    
    print(f"[*] Deploying NodeWorker to {LOCATION}...")
    print(f"[*] Bucket: {BUCKET}\n")
    
    from NodeWorker.agents.NodeWorker import KaedraAgent
    
    # Instantiate the REAL AGENT locally
    # Note: KaedraAgent.__init__ is effectively empty/safe (lazy loading).
    agent_instance = KaedraAgent()
    
    remote_app = reasoning_engines.ReasoningEngine.create(
        agent_instance,
        requirements=[
            "google-cloud-aiplatform>=1.79.0",
            "google-genai>=0.3.0",
            "google-cloud-storage>=2.14.0",
            "notion-client>=2.0.0",
            "httpx>=0.27.0",
            "pydantic>=2.0.0",
            "pytz>=2024.1",
            "python-dotenv>=1.0.0",
            "requests>=2.31.0",
            "beautifulsoup4>=4.12.0",
            "pillow>=10.0.0",
            "uvicorn>=0.23.0",
            "fastapi>=0.100.0",
            "cloudpickle>=3.0.0",
            "nest_asyncio>=1.5.0"
        ],
        sys_version="3.12", # Back to 3.12 (User confirmed Infra OK)
        extra_packages=["NodeWorker"], # CRITICAL FIX: Upload local package
        display_name="NodeWorker-v0.0.6-prod",
        description="NodeWorker - Strategic Intelligence Partner (Prod)"
    )
    
    print("\n✅ [SUCCESS] NodeWorker deployed!")
    print(f"📍 Resource: {remote_app.resource_name}\n")
    
    # Save ID
    with open("REASONING_ENGINE_ID.txt", "w") as f:
        f.write(remote_app.resource_name)
    
    print("Test with:")
    print(f'  response = remote_app.query("Yo, status check")')
