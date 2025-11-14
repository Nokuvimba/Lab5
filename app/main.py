from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, status, Response
from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine, SessionLocal
from .models import Base, UserDB, CourseDB, ProjectDB
from .schemas import (
    UserCreate, UserRead, UserUpdatePUT, UserUpdatePATCH,
    CourseCreate, CourseRead, CourseUpdatePUT, CourseUpdatePATCH,
    ProjectCreate, ProjectRead, ProjectUpdatePUT, ProjectUpdatePATCH,
    ProjectReadWithOwner, ProjectCreateForUser
)

#Replacing @app.on_event("startup")

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine) 
    yield

app = FastAPI(lifespan=lifespan)

# CORS (add this block)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # dev-friendly; tighten in prod
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def commit_or_rollback(db: Session, error_msg: str):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=error_msg)


# ------------------------------------------------------------
# Health
# ------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}


# ============================================================
# COURSES CRUD
# ============================================================
@app.post("/api/courses", response_model=CourseRead, status_code=201)
def create_course(course: CourseCreate, db: Session = Depends(get_db)):
    row = CourseDB(**course.model_dump())
    db.add(row)
    commit_or_rollback(db, "Course already exists")
    db.refresh(row)
    return row


@app.get("/api/courses", response_model=list[CourseRead])
def list_courses(limit: int = 10, offset: int = 0, db: Session = Depends(get_db)):
    stmt = select(CourseDB).order_by(CourseDB.id).limit(limit).offset(offset)
    return db.execute(stmt).scalars().all()


@app.get("/api/courses/{course_id}", response_model=CourseRead)
def get_course(course_id: int, db: Session = Depends(get_db)):
    row = db.get(CourseDB, course_id)
    if not row:
        raise HTTPException(status_code=404, detail="Course not found")
    return row


@app.put("/api/courses/{course_id}", response_model=CourseRead)
def put_course(course_id: int, payload: CourseUpdatePUT, db: Session = Depends(get_db)):
    row = db.get(CourseDB, course_id)
    if not row:
        raise HTTPException(status_code=404, detail="Course not found")

    row.code = payload.code
    row.name = payload.name
    row.credits = payload.credits

    commit_or_rollback(db, "Course update failed")
    db.refresh(row)
    return row


@app.patch("/api/courses/{course_id}", response_model=CourseRead)
def patch_course(course_id: int, payload: CourseUpdatePATCH, db: Session = Depends(get_db)):
    row = db.get(CourseDB, course_id)
    if not row:
        raise HTTPException(status_code=404, detail="Course not found")

    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(row, k, v)

    commit_or_rollback(db, "Course update failed")
    db.refresh(row)
    return row


@app.delete("/api/courses/{course_id}", status_code=204)
def delete_course(course_id: int, db: Session = Depends(get_db)):
    row = db.get(CourseDB, course_id)
    if not row:
        raise HTTPException(status_code=404, detail="Course not found")

    db.delete(row)
    db.commit()
    return Response(status_code=204)


# ============================================================
# PROJECTS CRUD
# ============================================================
@app.post("/api/projects", response_model=ProjectRead, status_code=201)
def create_project(project: ProjectCreate, db: Session = Depends(get_db)):
    owner = db.get(UserDB, project.owner_id)
    if not owner:
        raise HTTPException(status_code=404, detail="User not found")

    row = ProjectDB(**project.model_dump())
    db.add(row)
    commit_or_rollback(db, "Project creation failed")
    db.refresh(row)
    return row


@app.get("/api/projects", response_model=list[ProjectRead])
def list_projects(db: Session = Depends(get_db)):
    stmt = select(ProjectDB).order_by(ProjectDB.id)
    return db.execute(stmt).scalars().all()


@app.get("/api/projects/{project_id}", response_model=ProjectReadWithOwner)
def get_project_owner(project_id: int, db: Session = Depends(get_db)):
    stmt = (
        select(ProjectDB)
        .where(ProjectDB.id == project_id)
        .options(selectinload(ProjectDB.owner))
    )
    row = db.execute(stmt).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    return row


@app.put("/api/projects/{project_id}", response_model=ProjectRead)
def put_project(project_id: int, payload: ProjectUpdatePUT, db: Session = Depends(get_db)):
    row = db.get(ProjectDB, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")

    if payload.owner_id != row.owner_id:
        owner = db.get(UserDB, payload.owner_id)
        if not owner:
            raise HTTPException(status_code=404, detail="Owner not found")

    row.name = payload.name
    row.description = payload.description
    row.owner_id = payload.owner_id

    commit_or_rollback(db, "Project update failed")
    db.refresh(row)
    return row


@app.patch("/api/projects/{project_id}", response_model=ProjectRead)
def patch_project(project_id: int, payload: ProjectUpdatePATCH, db: Session = Depends(get_db)):
    row = db.get(ProjectDB, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")

    data = payload.model_dump(exclude_unset=True)

    if "owner_id" in data:
        owner = db.get(UserDB, data["owner_id"])
        if not owner:
            raise HTTPException(status_code=404, detail="Owner not found")

    for k, v in data.items():
        setattr(row, k, v)

    commit_or_rollback(db, "Project update failed")
    db.refresh(row)
    return row


@app.delete("/api/projects/{project_id}", status_code=204)
def delete_project(project_id: int, db: Session = Depends(get_db)):
    row = db.get(ProjectDB, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")

    db.delete(row)
    db.commit()
    return Response(status_code=204)


# Nested: list projects for a user
@app.get("/api/users/{user_id}/projects", response_model=list[ProjectRead])
def get_user_projects(user_id: int, db: Session = Depends(get_db)):
    stmt = select(ProjectDB).where(ProjectDB.owner_id == user_id)
    return db.execute(stmt).scalars().all()


# Nested: create project for a specific user
@app.post("/api/users/{user_id}/projects", response_model=ProjectRead, status_code=201)
def create_user_project(user_id: int, project: ProjectCreateForUser, db: Session = Depends(get_db)):
    user = db.get(UserDB, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    row = ProjectDB(name=project.name, description=project.description, owner_id=user_id)
    db.add(row)
    commit_or_rollback(db, "Project creation failed")
    db.refresh(row)
    return row


# ============================================================
# USERS CRUD
# ============================================================
@app.get("/api/users", response_model=list[UserRead])
def list_users(db: Session = Depends(get_db)):
    stmt = select(UserDB).order_by(UserDB.id)
    return db.execute(stmt).scalars().all()


@app.get("/api/users/{user_id}", response_model=UserRead)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.get(UserDB, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@app.post("/api/users", response_model=UserRead, status_code=201)
def add_user(payload: UserCreate, db: Session = Depends(get_db)):
    user = UserDB(**payload.model_dump())
    db.add(user)
    commit_or_rollback(db, "User already exists")
    db.refresh(user)
    return user


@app.delete("/api/users/{user_id}", status_code=204)
def delete_user(user_id: int, db: Session = Depends(get_db)):
    user = db.get(UserDB, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    db.delete(user)
    db.commit()
    return Response(status_code=204)


@app.put("/api/users/{user_id}", response_model=UserRead)
def put_user(user_id: int, payload: UserUpdatePUT, db: Session = Depends(get_db)):
    user = db.get(UserDB, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.name = payload.name
    user.email = payload.email
    user.age = payload.age
    user.student_id = payload.student_id

    commit_or_rollback(db, "User update failed")
    db.refresh(user)
    return user


@app.patch("/api/users/{user_id}", response_model=UserRead)
def patch_user(user_id: int, payload: UserUpdatePATCH, db: Session = Depends(get_db)):
    user = db.get(UserDB, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(user, k, v)

    commit_or_rollback(db, "User update failed")
    db.refresh(user)
    return user