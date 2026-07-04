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

# Agent Engine rejects env vars with empty values, so only pass ones that are set.
_env_vars = {
    "NVIDIA_API_KEY":          os.environ["NVIDIA_API_KEY"],
    "NVIDIA_PRIMARY_MODEL":    os.environ.get("NVIDIA_PRIMARY_MODEL", "nvidia/nemotron-3-super-120b-a12b"),
    "NVIDIA_FALLBACK_MODEL":   os.environ.get("NVIDIA_FALLBACK_MODEL", "meta/llama-3.3-70b-instruct"),
    # GOOGLE_CLOUD_PROJECT is reserved on Agent Engine — the runtime provides it.
    # The gateway itself is not reachable from outside its VM — the agent goes
    # through the backend's /agent/whatsapp/* relay instead (see skills/_backend.py).
    "BACKEND_API_URL":         os.environ.get("BACKEND_API_URL", ""),
    "AGENT_BACKEND_SECRET":    os.environ.get("AGENT_BACKEND_SECRET", ""),
    "DATABASE_URL":            os.environ.get("DATABASE_URL", ""),
    # Needed to refresh an org's Google token for Forms/Docs creation.
    "GOOGLE_OAUTH_CLIENT_ID":     os.environ.get("GOOGLE_OAUTH_CLIENT_ID", ""),
    "GOOGLE_OAUTH_CLIENT_SECRET": os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", ""),
}
_env_vars = {k: v for k, v in _env_vars.items() if v}

deployed = agent_engines.create(
    app,
    requirements=[
        # Provides the `vertexai` module the Agent Engine runtime needs to load
        # the pickled agent. Without it the container fails to start.
        "google-cloud-aiplatform[agent_engines]>=1.93.0",
        "google-adk>=0.3.0",
        "firebase-admin>=6.5.0",
        "litellm>=1.50.0",
        "httpx>=0.27.0",
        "python-dotenv>=1.0.0",
        "psycopg2-binary>=2.9.9",
    ],
    # Local source the pickled agent references by module — must be shipped to
    # the container or it fails to start with ModuleNotFoundError (skills, etc.).
    extra_packages=[
        "agent.py",
        "context.py",
        "authz.py",
        "observability.py",
        "demo_fallback.py",
        "skills",
    ],
    env_vars=_env_vars,
    display_name="fello-coordinator",
)

print("\n✓ Deployed successfully!")
print(f"  Resource name: {deployed.resource_name}")
print("\nAdd this to fello-frontend/.env.local:")
print(f"  AGENT_ENGINE_RESOURCE_NAME={deployed.resource_name}")
