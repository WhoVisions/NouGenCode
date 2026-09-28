
import os
from google import genai
from google.genai import types
from pathlib import Path

def ingest_pdf():
    # Use the project's config or env for project ID
    PROJECT_ID = os.environ.get("PROJECT_ID", "default-project")
    client = genai.Client(vertexai=True, project=PROJECT_ID, location="global")
    
    pdf_path = r"c:\Users\super\Downloads\Studying_Contemporary_American_Film_A_Guide_To_Movie_Analysis_Thomas_Elsaesser__Warren_Buckl.pdf"
    
    if not os.path.exists(pdf_path):
        print(f"File not found: {pdf_path}")
        return

    print(f"Ingesting PDF: {pdf_path}")
    
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    prompt = """
    Analyze this film analysis book: 'Studying Contemporary American Film'.
    Extract the 10 most critical higher-level frameworks or criteria that an AI Review Board should use to evaluate a narrative's 'cinematic quality'.
    Focus on:
    1. Narrative Logic & Symmetry.
    2. Spectator Position (POV immersion).
    3. Genre Hybridity/Subversion.
    4. Subtextual/Ideological layers.
    5. Structural Innovation.
    
    Format as a list of directives for an AI agent.
    """
    
    try:
        response = client.models.generate_content(
            model="gemini-1.5-pro-002", # Vertex AI specific model name
            contents=[
                types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
                prompt
            ]
        )
        
        output_path = Path("NodeWorker/config/film_theory_directives.txt")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(response.text, encoding="utf-8")
        print(f"Directives saved to {output_path}")
        print("\nSUMMARY OF EXTRACTED FRAMEWORKS:")
        print(response.text[:1000] + "...")
        
    except Exception as e:
        print(f"Error ingest PDF: {e}")

if __name__ == "__main__":
    ingest_pdf()
