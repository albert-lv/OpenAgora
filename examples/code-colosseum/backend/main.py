"""Code Colosseum orchestrator backend."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.arena_client_wrapper import ArenaWrapper
from backend.benchmark import BenchmarkEngine
from backend.duel import DuelEngine
from backend.elo import EloService
from backend.problems import get_problem, load_problems
from backend.training import TrainingService


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.arena = ArenaWrapper()
    app.state.elo = EloService()
    app.state.engine = DuelEngine(arena=app.state.arena, elo_service=app.state.elo)
    app.state.benchmark = BenchmarkEngine(arena=app.state.arena)
    app.state.training = TrainingService()
    yield
    app.state.arena.close()


app = FastAPI(title="Code Colosseum Orchestrator", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class DuelRequest(BaseModel):
    problem_id: str
    agent_a_name: str = "Agent A"
    agent_b_name: str = "Agent B"
    agent_a_type: str = "mock"
    agent_b_type: str = "mock"


class BenchmarkRequest(BaseModel):
    agent_types: list[str] | None = None
    problem_ids: list[str] | None = None


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/problems")
def list_problems():
    problems = load_problems()
    return {"problems": [p.to_dict() for p in problems.values()]}


@app.get("/api/problems/{problem_id}")
def get_problem_detail(problem_id: str):
    problem = get_problem(problem_id)
    if not problem:
        raise HTTPException(status_code=404, detail="Problem not found")
    return problem.to_dict(include_tests=True)


@app.post("/api/duels")
async def create_duel(req: DuelRequest):
    problem = get_problem(req.problem_id)
    if not problem:
        raise HTTPException(status_code=404, detail="Problem not found")
    duel = await app.state.engine.start_duel(
        problem,
        agent_a_name=req.agent_a_name,
        agent_b_name=req.agent_b_name,
        agent_a_type=req.agent_a_type,
        agent_b_type=req.agent_b_type,
    )
    return {"duel_id": duel.id, "status": duel.status}


@app.get("/api/duels")
def list_duels():
    return {"duels": app.state.engine.list_duels()}


@app.get("/api/duels/{duel_id}")
def get_duel(duel_id: str):
    detail = app.state.engine.get_duel_detail(duel_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Duel not found")
    return detail


@app.get("/api/duels/{duel_id}/stream")
async def stream_duel(duel_id: str):
    duel = app.state.engine.get_duel(duel_id)
    if not duel:
        raise HTTPException(status_code=404, detail="Duel not found")

    async def event_generator():
        while True:
            try:
                event = await asyncio.wait_for(duel.events.get(), timeout=60.0)
                yield f"data: {__import__('json').dumps(event)}\n\n"
                if event.get("type") == "done":
                    break
            except asyncio.TimeoutError:
                yield f"data: {__import__('json').dumps({'type': 'heartbeat'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/leaderboard")
def get_leaderboard():
    return {"leaderboard": app.state.elo.leaderboard()}


@app.get("/api/rollouts/{rollout_id}/trajectory")
def get_rollout_trajectory(rollout_id: str):
    """Return the full LLM trajectory for a rollout.

    This is the key data-plane feature: every LLM request/response that the
    Arena proxy captured is exposed here for inspection and debugging.
    """
    try:
        trajectory = app.state.arena.get_trajectory(rollout_id)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch trajectory: {e}"
        ) from e
    if not trajectory:
        raise HTTPException(status_code=404, detail="Trajectory not found")
    return {"rollout_id": rollout_id, "trajectory": trajectory}


@app.get("/api/training/status")
def get_training_status():
    return {"status": app.state.training.latest_status()}


@app.post("/api/training/metrics")
def append_training_metric(record: dict):
    app.state.training.append(record)
    return {"status": "ok"}


@app.get("/api/training/stream")
async def stream_training():
    """Stream training metrics as they are appended in real time."""
    queue = app.state.training.subscribe()

    async def event_generator():
        # Send current history first so the client can render immediately.
        status = app.state.training.latest_status()
        for record in status.get("history", []):
            yield f"data: {__import__('json').dumps(record)}\n\n"

        while True:
            try:
                record = await asyncio.wait_for(queue.get(), timeout=60.0)
                yield f"data: {__import__('json').dumps(record)}\n\n"
            except asyncio.TimeoutError:
                yield f"data: {__import__('json').dumps({'type': 'heartbeat'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/benchmarks")
async def create_benchmark(req: BenchmarkRequest):
    problems = load_problems()
    selected_problem_ids = req.problem_ids or list(problems.keys())
    selected_problems = [
        problems[pid] for pid in selected_problem_ids if pid in problems
    ]
    if not selected_problems:
        raise HTTPException(status_code=400, detail="No valid problems selected")

    agent_types = req.agent_types or ["mock"]
    benchmark = await app.state.benchmark.start_benchmark(
        selected_problems,
        agent_types,
    )
    return {"benchmark_id": benchmark.id, "status": benchmark.status}


@app.get("/api/benchmarks")
def list_benchmarks():
    return {"benchmarks": app.state.benchmark.list_benchmarks()}


@app.get("/api/benchmarks/{benchmark_id}")
def get_benchmark(benchmark_id: str):
    detail = app.state.benchmark.get_benchmark_detail(benchmark_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    return detail


@app.get("/api/benchmarks/{benchmark_id}/stream")
async def stream_benchmark(benchmark_id: str):
    benchmark = app.state.benchmark.get_benchmark(benchmark_id)
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    async def event_generator():
        while True:
            try:
                event = await asyncio.wait_for(benchmark.events.get(), timeout=60.0)
                yield f"data: {__import__('json').dumps(event)}\n\n"
                if event.get("type") == "done":
                    break
            except asyncio.TimeoutError:
                yield f"data: {__import__('json').dumps({'type': 'heartbeat'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
