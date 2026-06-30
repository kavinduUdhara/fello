"""Deploy the Fello agent to Vertex AI Agent Engine.

Run once:
  python deploy.py

Then copy the printed resource_name into .env.local as AGENT_ENGINE_RESOURCE_NAME.

Prerequisites:
  gcloud auth application-default login
  gsutil mb gs://fello-pt-agent-staging   (only needed once)
  pip install -r requirements.txt
"""

import os
from dotenv import load_dotenv
load_dotenv()

import vertexai
from vertexai import agent_engines
from vertexai.agent_engines import AdkApp

# Import the agent AFTER env is loaded
from agent import root_agent

PROJECT   = os.environ.get("GOOGLE_CLOUD_PROJECT", "fello-pt")
LOCATION  = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
BUCKET    = os.environ.get("GCS_STAGING_BUCKET", "gs://fello-pt-agent-staging")

print(f"Deploying to project={PROJECT}  location={LOCATION}  bucket={BUCKET}")

vertexai.init(project=PROJECT, location=LOCATION, staging_bucket=BUCKET)

app = AdkApp(agent=root_agent, enable_tracing=False)

deployed = agent_engines.create(
    app,
    requirements=[
        "google-adk>=0.3.0",
        "firebase-admin>=6.5.0",
        "litellm>=1.50.0",
        "httpx>=0.27.0",
        "python-dotenv>=1.0.0",
        "psycopg2-binary>=2.9.9",
    ],
    env_vars={
        "NVIDIA_API_KEY":          os.environ["NVIDIA_API_KEY"],
        "NVIDIA_PRIMARY_MODEL":    os.environ.get("NVIDIA_PRIMARY_MODEL", "thudm/glm-4-9b-chat"),
        "NVIDIA_FALLBACK_MODEL":   os.environ.get("NVIDIA_FALLBACK_MODEL", "minimax/minimax-text-01"),
        "GOOGLE_CLOUD_PROJECT":    PROJECT,
        "BAILEYS_API_URL":         os.environ.get("BAILEYS_API_URL", ""),
        "BAILEYS_API_SECRET":      os.environ.get("BAILEYS_API_SECRET", ""),
        "DATABASE_URL":            os.environ.get("DATABASE_URL", ""),
    },
    display_name="fello-coordinator",
)

print("\n✓ Deployed successfully!")
print(f"  Resource name: {deployed.resource_name}")
print("\nAdd this to fello-frontend/.env.local:")
print(f"  AGENT_ENGINE_RESOURCE_NAME={deployed.resource_name}")
