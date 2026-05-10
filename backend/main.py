"""
DevOps CRUD Chatbot - FastAPI Backend
Production-ready with JWT auth, database integration, and streaming AI responses
"""

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware

HTTPAuthCredential = HTTPAuthorizationCredentials
from pydantic import BaseModel
from datetime import datetime, timedelta
import jwt
import os
from typing import Optional
import json
import asyncio

# Persistent storage (SQLite by default)
# If DATABASE_URL is set to sqlite:///... we will use SQLite.
# Current implementation focuses on SQLite to make local + docker working reliably.

from backend.db import sqlite_path_from_url, init_sqlite
from backend.auth import hash_password, verify_password
from backend.repo import Repo

DB_URL = os.getenv("DATABASE_URL", "sqlite:///./devops_crud.db")

_sqlite_path = sqlite_path_from_url(DB_URL)
if not _sqlite_path:
    raise RuntimeError(
        "Only sqlite DATABASE_URL is supported in this snapshot. "
        "Set DATABASE_URL=sqlite:///./devops_crud.db for local runs."
    )

init_sqlite(_sqlite_path)
repo = Repo(_sqlite_path)


# Configuration

SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Initialize FastAPI app
app = FastAPI(
    title="DevOps CRUD Chatbot API",
    description="Full-stack DevOps application with AI chatbot",
    version="1.0.0"
)

# CORS middleware
# NOTE: Never use wildcard origins with credentials.
cors_origins = os.getenv("CORS_ORIGINS")
if cors_origins:
    allow_origins = [o.strip() for o in cors_origins.split(",") if o.strip()]
else:
    # Local dev + Render frontend (edit this list if you change frontend URL)
    allow_origins = ["http://localhost:5173", "https://devops-crud-chatbot-1.onrender.com"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


security = HTTPBearer()


def _ensure_str(x: Optional[object]) -> Optional[str]:
    if x is None:
        return None
    return str(x)


# ============ Pydantic Models ============

class UserRegister(BaseModel):
    # Use plain str to avoid extra email-validator dependency in this demo.
    email: str
    password: str
    full_name: str

class UserLogin(BaseModel):
    email: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict

class Task(BaseModel):
    id: Optional[str] = None
    title: str
    description: str
    status: str = "pending"  # pending, in_progress, completed
    priority: str = "medium"  # low, medium, high
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

class ChatMessage(BaseModel):
    message: str
    context: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    timestamp: str

# ============ Helper Functions ============

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create JWT token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(credentials: HTTPAuthCredential = Depends(security)):
    """Verify JWT token"""
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return email
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

# ============ Authentication Endpoints ============

@app.post("/api/auth/register", response_model=Token)
async def register(user: UserRegister):
    """Register a new user"""
    existing = repo.get_user_by_email(user.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    password_hash = hash_password(user.password)
    repo.create_user(email=user.email, password_hash=password_hash, full_name=user.full_name)

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": user.email}, expires_delta=access_token_expires)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "email": user.email,
            "full_name": user.full_name,
        },
    }


@app.post("/api/auth/login", response_model=Token)
async def login(user: UserLogin):
    """Login user and return JWT token"""
    stored_user = repo.get_user_by_email(user.email)
    if not stored_user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(user.password, stored_user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": user.email}, expires_delta=access_token_expires)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "email": user.email,
            "full_name": stored_user["full_name"],
        },
    }


@app.get("/api/auth/me")
async def get_current_user(email: str = Depends(verify_token)):
    """Get current user info"""
    user = repo.get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "email": user["email"],
        "full_name": user["full_name"],
        "created_at": user["created_at"],
    }


# ============ CRUD Tasks Endpoints ============

@app.post("/api/tasks", response_model=Task)
async def create_task(task: Task, email: str = Depends(verify_token)):
    """Create a new task"""
    # Use stable id generation based on current DB row count
    task_id = f"task_{repo.count_tasks() + 1}"

    created = repo.create_task(
        owner=email,
        task_id=task_id,
        title=task.title,
        description=task.description,
        status=task.status,
        priority=task.priority,
    )
    # Repo returns DB row including owner
    return created


@app.get("/api/tasks")
async def get_tasks(email: str = Depends(verify_token)):
    """Get all tasks for current user"""
    user_tasks = repo.list_tasks_for_owner(email)
    return {"tasks": user_tasks}


@app.get("/api/tasks/{task_id}", response_model=Task)
async def get_task(task_id: str, email: str = Depends(verify_token)):
    """Get a specific task"""
    task = repo.get_task_for_owner(owner=email, task_id=task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return task


@app.put("/api/tasks/{task_id}", response_model=Task)
async def update_task(task_id: str, task: Task, email: str = Depends(verify_token)):
    """Update a task"""
    stored = repo.get_task_for_owner(owner=email, task_id=task_id)
    if not stored:
        raise HTTPException(status_code=404, detail="Task not found")

    updated = repo.update_task_for_owner(
        owner=email,
        task_id=task_id,
        title=task.title or stored["title"],
        description=task.description if task.description is not None else stored["description"],
        status=task.status or stored["status"],
        priority=task.priority or stored["priority"],
    )
    return updated


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str, email: str = Depends(verify_token)):
    """Delete a task"""
    deleted = repo.delete_task_for_owner(owner=email, task_id=task_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"message": "Task deleted successfully"}


# ============ AI Chatbot Endpoints ============

@app.post("/api/chat")
async def chat_stream(msg: ChatMessage, email: str = Depends(verify_token)):
    """Chat endpoint with AI responses"""
    message_id = f"msg_{repo.count_messages() + 1}"
    now = datetime.utcnow().isoformat()

    # Persist message
    repo.create_message(user=email, message_id=message_id, message=msg.message, context=msg.context)

    # Generate AI response based on context
    response_text = await generate_devops_response(msg.message, msg.context)

    return {
        "message_id": message_id,
        "response": response_text,
        "timestamp": now,
    }


async def generate_devops_response(user_message: str, context: Optional[str] = None) -> str:
    """Generate DevOps-relevant AI responses"""
    message_lower = user_message.lower()
    
    # DevOps-specific responses
    devops_responses = {
        "kubernetes": "Kubernetes is a container orchestration platform. Key concepts: Pods, Services, Deployments, ConfigMaps, and StatefulSets. Would you like to know about cluster setup, scaling, or troubleshooting?",
        "docker": "Docker enables containerization. Best practices: use multi-stage builds, minimize layers, scan for vulnerabilities. Need help with Dockerfile optimization or image deployment?",
        "terraform": "Terraform is infrastructure as code. Core concepts: resources, modules, state management. Would you like help with AWS, Azure, or GCP provisioning?",
        "ci/cd": "CI/CD pipelines automate testing and deployment. Common tools: GitHub Actions, Jenkins, GitLab CI. Let's discuss your pipeline requirements.",
        "aws": "AWS offers 200+ services. Key for DevOps: EC2, RDS, S3, Lambda, ECS/EKS. Which service would you like to explore?",
        "monitoring": "Monitoring stack: Prometheus for metrics, Grafana for dashboards, ELK for logs. How can I help you set this up?",
        "security": "Security practices: SAST, DAST, secret scanning, compliance checks. What aspect interests you most?",
    }
    
    for key, response in devops_responses.items():
        if key in message_lower:
            return response
    
    # Default helpful response
    return f"I'm your DevOps assistant. You asked: '{user_message}'. I can help with: Kubernetes, Docker, Terraform, CI/CD, AWS, Monitoring, and Security. What would you like to know more about?"

# ============ Health & Analytics ============

@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "users": repo.count_users(),
        "tasks": repo.count_tasks(),
        "messages": repo.count_messages(),
    }


@app.get("/api/stats")
async def get_stats(email: str = Depends(verify_token)):
    """Get user statistics"""
    user_tasks = repo.list_tasks_for_owner(email)

    completed = len([t for t in user_tasks if t["status"] == "completed"])
    in_progress = len([t for t in user_tasks if t["status"] == "in_progress"])
    pending = len([t for t in user_tasks if t["status"] == "pending"])

    return {
        "total_tasks": len(user_tasks),
        "completed": completed,
        "in_progress": in_progress,
        "pending": pending,
        "completion_rate": (completed / len(user_tasks) * 100) if user_tasks else 0,
    }


# ============ Root & Documentation ============


@app.get("/")
async def root():
    """Root endpoint with API info"""
    return {
        "app": "DevOps CRUD Chatbot",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/api/health"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
