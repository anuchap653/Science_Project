import io
import random
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

import altair as alt
import matplotlib.pyplot as plt
import pandas as pd
import qrcode
import streamlit as st


GRID_SIZE = 20
MAX_CELLS = GRID_SIZE * GRID_SIZE
ENTITY_PRIORITY = {"GRASS": 1, "RABBIT": 2, "WOLF": 3}
ENTITY_MARKER = {"GRASS": "s", "RABBIT": "o", "WOLF": "^"}
ENTITY_COLOR = {"GRASS": "#2ECC71", "RABBIT": "#FFFFFF", "WOLF": "#E53935"}
DB_PATH = Path(__file__).parent / "votes.db"
TICK_SECONDS = 1.0
RABBIT_CAPACITY = 230
WOLF_CAPACITY = 70
VOTE_WINDOW_TICKS = 10
VOTE_EFFECT_AMOUNT = 6
WIN_MATCH_TICKS = 60
STABILITY_BLEND = 0.82
PRESET_SCENARIOS = {
    "สมดุล (แนะนำ)": (220, 50, 12),
    "เครียดจากภัยแล้ง": (140, 42, 14),
    "ผู้ล่าล้นระบบ": (170, 45, 28),
}
ACTION_LABELS = {
    "FOREST FIRE": "ไฟป่า",
    "DROUGHT": "ภัยแล้ง",
    "VACCINE DRIVE": "รณรงค์วัคซีน",
    "MIGRATE IN PREY": "อพยพเหยื่อเข้า",
}
ACTION_DESCRIPTIONS = {
    "FOREST FIRE": "ไฟป่า: หญ้าลดลงมาก และกระต่ายลดลงเล็กน้อย",
    "DROUGHT": "ภัยแล้ง: หญ้าลดลงต่อเนื่องจากน้ำไม่พอ",
    "VACCINE DRIVE": "รณรงค์วัคซีน: เพิ่มอัตรารอดของกระต่ายและหมาป่า",
    "MIGRATE IN PREY": "อพยพเหยื่อเข้า: เพิ่มจำนวนกระต่ายแบบฉับพลัน",
}


@dataclass
class SimulationState:
    tick: int
    grass: int
    rabbits: int
    wolves: int
    history: list[dict[str, int]]
    rabbits_xy: list[tuple[int, int]]
    wolves_xy: list[tuple[int, int]]
    grass_xy: list[tuple[int, int]]
    running: bool
    rabbit_team_score: int
    wolf_team_score: int


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS votes (
                voter_id TEXT PRIMARY KEY,
                choice TEXT NOT NULL CHECK(choice IN ('boost_rabbits', 'boost_wolves')),
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        table_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='votes'"
        ).fetchone()
        if table_sql and table_sql[0] and ("increase_grass" in table_sql[0] or "decrease_grass" in table_sql[0]):
            conn.execute(
                """
                CREATE TABLE votes_new (
                    voter_id TEXT PRIMARY KEY,
                    choice TEXT NOT NULL CHECK(choice IN ('boost_rabbits', 'boost_wolves')),
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                INSERT INTO votes_new (voter_id, choice, updated_at)
                SELECT
                    voter_id,
                    CASE
                        WHEN choice IN ('boost_rabbits', 'increase_grass') THEN 'boost_rabbits'
                        ELSE 'boost_wolves'
                    END,
                    updated_at
                FROM votes
                """
            )
            conn.execute("DROP TABLE votes")
            conn.execute("ALTER TABLE votes_new RENAME TO votes")
        conn.commit()


def save_vote(voter_id: str, choice: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO votes (voter_id, choice, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(voter_id) DO UPDATE SET
                choice = excluded.choice,
                updated_at = CURRENT_TIMESTAMP
            """,
            (voter_id.strip(), choice),
        )
        conn.commit()


def reset_votes() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM votes")
        conn.commit()


def get_vote_stats() -> tuple[int, int, int, int, int]:
    with sqlite3.connect(DB_PATH) as conn:
        counts = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT choice, COUNT(*) FROM votes GROUP BY choice"
            ).fetchall()
        }
    rabbit_votes = counts.get("boost_rabbits", 0)
    wolf_votes = counts.get("boost_wolves", 0)
    total = rabbit_votes + wolf_votes
    rabbit_pct = round((rabbit_votes / total) * 100) if total else 0
    wolf_pct = round((wolf_votes / total) * 100) if total else 0
    return rabbit_votes, wolf_votes, total, rabbit_pct, wolf_pct


def make_qr_image(url: str):
    img = qrcode.make(url)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def random_cells(count: int, grid_size: int) -> list[tuple[int, int]]:
    cells = [(x, y) for x in range(grid_size) for y in range(grid_size)]
    random.shuffle(cells)
    return cells[: max(0, min(count, len(cells)))]


def move_entities(points: list[tuple[int, int]], grid_size: int) -> list[tuple[int, int]]:
    moved = []
    for x, y in points:
        dx, dy = random.choice([(0, 1), (0, -1), (1, 0), (-1, 0), (0, 0)])
        moved.append(((x + dx) % grid_size, (y + dy) % grid_size))
    return moved


def initialize_simulation(grass: int, rabbits: int, wolves: int) -> SimulationState:
    grass = max(0, min(grass, MAX_CELLS))
    rabbits = max(0, min(rabbits, MAX_CELLS))
    wolves = max(0, min(wolves, MAX_CELLS))
    return SimulationState(
        tick=0,
        grass=grass,
        rabbits=rabbits,
        wolves=wolves,
        history=[{"tick": 0, "grass": grass, "rabbits": rabbits, "wolves": wolves}],
        rabbits_xy=random_cells(rabbits, GRID_SIZE),
        wolves_xy=random_cells(wolves, GRID_SIZE),
        grass_xy=random_cells(grass, GRID_SIZE),
        running=False,
        rabbit_team_score=0,
        wolf_team_score=0,
    )


def run_tick(state: SimulationState, rabbit_votes: int, wolf_votes: int, total_votes: int) -> None:
    grass = float(state.grass)
    rabbits = float(state.rabbits)
    wolves = float(state.wolves)

    # GRASS: logistic growth - grazing
    grass_growth_rate = random.uniform(0.10, 0.16)
    grass_growth = grass_growth_rate * grass * (1.0 - (grass / MAX_CELLS))
    grazing = 0.52 * rabbits * (grass / MAX_CELLS)
    grass_noise = random.uniform(-0.8, 0.8)
    next_grass = max(0.0, min(MAX_CELLS, grass + grass_growth - grazing + grass_noise))

    # RABBITS: births depend on food; deaths from natural causes + predation + starvation
    food_per_rabbit = grass / (rabbits + 1.0)
    food_factor = max(0.0, min(1.2, food_per_rabbit / 3.0))
    rabbit_births = random.uniform(0.22, 0.30) * rabbits * food_factor * (1.0 - (rabbits / RABBIT_CAPACITY))
    predation = random.uniform(0.55, 0.75) * wolves * (rabbits / (rabbits + 25.0))
    rabbit_natural_deaths = random.uniform(0.02, 0.04) * rabbits
    rabbit_starvation = random.uniform(0.10, 0.18) * rabbits * max(0.0, 1.0 - food_factor)
    next_rabbits = max(
        0.0,
        min(
            RABBIT_CAPACITY,
            rabbits + rabbit_births - predation - rabbit_natural_deaths - rabbit_starvation,
        ),
    )

    # WOLVES: births depend on successful hunts; starvation grows when prey is scarce
    prey_per_wolf = rabbits / (wolves + 1.0)
    wolf_births = random.uniform(0.20, 0.30) * predation
    wolf_natural_deaths = random.uniform(0.06, 0.10) * wolves
    wolf_starvation = random.uniform(0.12, 0.20) * wolves * max(0.0, 1.0 - (prey_per_wolf / 2.8))
    next_wolves = max(
        0.0,
        min(
            WOLF_CAPACITY,
            wolves + wolf_births - wolf_natural_deaths - wolf_starvation,
        ),
    )

    # Smooth per-tick changes to keep classroom gameplay stable and readable.
    next_grass = (1.0 - STABILITY_BLEND) * grass + STABILITY_BLEND * next_grass
    next_rabbits = (1.0 - STABILITY_BLEND) * rabbits + STABILITY_BLEND * next_rabbits
    next_wolves = (1.0 - STABILITY_BLEND) * wolves + STABILITY_BLEND * next_wolves

    state.grass = int(round(next_grass))
    state.rabbits = int(round(next_rabbits))
    state.wolves = int(round(next_wolves))

    state.tick += 1

    # Apply vote effect in windows (countdown gameplay): every VOTE_WINDOW_TICKS.
    if total_votes > 0 and state.tick % VOTE_WINDOW_TICKS == 0:
        if rabbit_votes > wolf_votes:
            state.rabbits = min(RABBIT_CAPACITY, state.rabbits + VOTE_EFFECT_AMOUNT)
            state.rabbit_team_score += 1
        elif wolf_votes > rabbit_votes:
            state.wolves = min(WOLF_CAPACITY, state.wolves + VOTE_EFFECT_AMOUNT)
            state.wolf_team_score += 1

    state.rabbits_xy = move_entities(random_cells(state.rabbits, GRID_SIZE), GRID_SIZE)
    state.wolves_xy = move_entities(random_cells(state.wolves, GRID_SIZE), GRID_SIZE)
    state.grass_xy = random_cells(state.grass, GRID_SIZE)
    state.history.append(
        {"tick": state.tick, "grass": state.grass, "rabbits": state.rabbits, "wolves": state.wolves}
    )


def apply_disaster_or_action(state: SimulationState, action: str) -> None:
    if action == "FOREST FIRE":
        state.grass = max(0, int(state.grass * 0.45))
        state.rabbits = max(0, int(state.rabbits * 0.9))
    elif action == "DROUGHT":
        state.grass = max(0, int(state.grass * 0.65))
    elif action == "VACCINE DRIVE":
        state.rabbits = min(MAX_CELLS, int(state.rabbits * 1.12))
        state.wolves = min(MAX_CELLS, int(state.wolves * 1.06))
    elif action == "MIGRATE IN PREY":
        state.rabbits = min(MAX_CELLS, state.rabbits + random.randint(8, 22))


def evaluate_round_outcome(state: SimulationState) -> tuple[str, str]:
    if state.grass <= 0:
        return "critical", "ผลลัพธ์ท้ายรอบ: ระบบล่ม — ผู้ผลิตหมด (หญ้า = 0)"
    if state.rabbits <= 0 and state.wolves <= 0:
        return "critical", "ผลลัพธ์ท้ายรอบ: ระบบล่ม — ผู้บริโภคสูญพันธุ์ทั้งหมด"
    if state.rabbits <= 0:
        return "warning", "ผลลัพธ์ท้ายรอบ: ไม่สมดุล — กระต่ายสูญพันธุ์"
    if state.wolves <= 0:
        return "warning", "ผลลัพธ์ท้ายรอบ: ไม่สมดุล — หมาป่าสูญพันธุ์"
    if state.tick < 8:
        return "info", "ผลลัพธ์ท้ายรอบ: กำลังสะสมข้อมูลเพื่อประเมินเสถียรภาพ"

    recent = state.history[-8:]
    grass_range = max(row["grass"] for row in recent) - min(row["grass"] for row in recent)
    rabbit_range = max(row["rabbits"] for row in recent) - min(row["rabbits"] for row in recent)
    wolf_range = max(row["wolves"] for row in recent) - min(row["wolves"] for row in recent)
    if grass_range <= 60 and rabbit_range <= 24 and wolf_range <= 12:
        return "success", "ผลลัพธ์ท้ายรอบ: สมดุลค่อนข้างคงที่"
    return "info", "ผลลัพธ์ท้ายรอบ: ระบบยังผันผวน (ยังไม่เข้าสมดุล)"


def render_icon_map(state: SimulationState) -> None:
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.set_xlim(-0.5, GRID_SIZE - 0.5)
    ax.set_ylim(-0.5, GRID_SIZE - 0.5)
    ax.invert_yaxis()
    ax.set_xticks(range(0, GRID_SIZE, 2))
    ax.set_yticks(range(0, GRID_SIZE, 2))
    ax.grid(alpha=0.2)
    ax.set_aspect("equal")
    ax.set_facecolor("#f8fafc")
    fig.patch.set_facecolor("#f8fafc")
    ax.set_xlabel("")
    ax.set_ylabel("")

    cell_entity: dict[tuple[int, int], str] = {}
    layers = (
        [("GRASS", pt) for pt in state.grass_xy]
        + [("RABBIT", pt) for pt in state.rabbits_xy]
        + [("WOLF", pt) for pt in state.wolves_xy]
    )
    for entity, pt in layers:
        existing = cell_entity.get(pt)
        if existing is None or ENTITY_PRIORITY[entity] >= ENTITY_PRIORITY[existing]:
            cell_entity[pt] = entity

    for entity in ["GRASS", "RABBIT", "WOLF"]:
        points = [pt for pt, e in cell_entity.items() if e == entity]
        if not points:
            continue
        xs = [x for x, _ in points]
        ys = [y for _, y in points]
        ax.scatter(
            xs,
            ys,
            s=90,
            marker=ENTITY_MARKER[entity],
            c=ENTITY_COLOR[entity],
            edgecolors="#111827",
            linewidths=0.5,
            label=entity,
        )

    ax.legend(loc="upper right", frameon=True, fontsize=9)
    ax.set_title("GRASS / RABBIT / WOLF", fontsize=11, pad=12)
    st.pyplot(fig, width="stretch")
    plt.close(fig)


def render_vote_page() -> None:
    st.title("Class Voting Portal")
    st.caption(f"Vote locks every {VOTE_WINDOW_TICKS} seconds. You can switch sides anytime before lock.")

    team_col1, team_col2 = st.columns(2)
    with team_col1:
        st.info("🐇 **Team Rabbit**\n\nWin support to boost rabbit population.")
    with team_col2:
        st.warning("🐺 **Team Wolf**\n\nWin support to boost wolf population.")

    with st.form("vote_form", clear_on_submit=False):
        voter_id = st.text_input("Your Name or Student ID")
        choice_label = st.radio("Your Vote", ["Team Rabbit (+Rabbits)", "Team Wolf (+Wolves)"], horizontal=True)
        submitted = st.form_submit_button("Submit / Change Vote", width="stretch")
    if submitted:
        if not voter_id.strip():
            st.toast("Please enter your name or student ID before submitting.", icon="⚠️")
        else:
            choice = "boost_rabbits" if choice_label == "Team Rabbit (+Rabbits)" else "boost_wolves"
            save_vote(voter_id, choice)
            st.toast("Vote updated successfully.", icon="✅")

    rabbit_votes, wolf_votes, total, rabbit_pct, wolf_pct = get_vote_stats()
    metrics = st.columns(3)
    metrics[0].metric("Total Voters", total)
    metrics[1].metric("Rabbit Team", rabbit_votes)
    metrics[2].metric("Wolf Team", wolf_votes)

    if total == 0:
        st.markdown("**CURRENT VOTE:** ยังไม่มีการโหวต")
    else:
        st.markdown(f"**CURRENT VOTE:** TEAM RABBIT (**{rabbit_pct}%**) vs. TEAM WOLF (**{wolf_pct}%**)")
    st.progress(rabbit_pct / 100 if total else 0.0, text=f"Team Rabbit {rabbit_pct}%")
    st.progress(wolf_pct / 100 if total else 0.0, text=f"Team Wolf {wolf_pct}%")

    stats = pd.DataFrame(
        [
            {"choice": "Team Rabbit", "count": rabbit_votes},
            {"choice": "Team Wolf", "count": wolf_votes},
        ]
    )
    chart = (
        alt.Chart(stats)
        .mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6)
        .encode(
            x=alt.X("choice:N", title=""),
            y=alt.Y("count:Q", title="VOTERS"),
            color=alt.Color("choice:N", scale=alt.Scale(range=["#2ECC71", "#F39C12"]), legend=None),
        )
        .properties(height=260)
    )
    st.altair_chart(chart, width="stretch")


def render_dashboard(
    state: SimulationState,
    rabbit_votes: int,
    wolf_votes: int,
    total_votes: int,
    rabbit_pct: int,
    wolf_pct: int,
) -> None:
    st.title("Live Population Simulator")
    st.caption("Science class project • Streamlit")

    main_col, vote_col = st.columns([3, 1.3], vertical_alignment="top")

    with main_col:
        st.subheader("ECOSYSTEM HEALTH DASHBOARD")
        history_df = pd.DataFrame(state.history)
        chart_df = history_df.melt(id_vars="tick", var_name="population", value_name="count")
        color_scale = alt.Scale(
            domain=["grass", "rabbits", "wolves"],
            range=["#2ECC71", "#FFFFFF", "#E53935"],
        )
        line = (
            alt.Chart(chart_df)
            .mark_line(point=True, strokeWidth=3)
            .encode(
                x=alt.X("tick:Q", title="TIME (TICKS)"),
                y=alt.Y("count:Q", title="POPULATION"),
                color=alt.Color("population:N", title="", scale=color_scale),
            )
            .properties(height=330)
        )
        st.altair_chart(line, width="stretch")

    with vote_col:
        st.subheader("REAL-TIME VOTING SYSTEM")
        ticks_to_lock = VOTE_WINDOW_TICKS - (state.tick % VOTE_WINDOW_TICKS)
        st.caption(f"Vote locks in **{ticks_to_lock}** tick(s)")
        vote_df = pd.DataFrame(
            [
                {"choice": "Team Rabbit", "count": rabbit_votes, "percent": rabbit_pct},
                {"choice": "Team Wolf", "count": wolf_votes, "percent": wolf_pct},
            ]
        )
        vote_chart = (
            alt.Chart(vote_df)
            .mark_bar()
            .encode(
                x=alt.X("choice:N", title=""),
                y=alt.Y("percent:Q", title="VOTE (%)", scale=alt.Scale(domain=[0, 100])),
                color=alt.Color("choice:N", scale=alt.Scale(range=["#2ECC71", "#F39C12"]), legend=None),
            )
            .properties(height=260)
        )
        st.altair_chart(vote_chart, width="stretch")
        if total_votes == 0:
            st.markdown("**CURRENT VOTE:** ยังไม่มีการโหวต")
        else:
            st.markdown(f"**CURRENT VOTE:** TEAM RABBIT (**{rabbit_pct}%**) vs. TEAM WOLF (**{wolf_pct}%**)")
        st.metric("Total Voters", total_votes)
        st.metric("Latest Tick", state.tick)
        score_cols = st.columns(2)
        score_cols[0].metric("Rabbit Team Score", state.rabbit_team_score)
        score_cols[1].metric("Wolf Team Score", state.wolf_team_score)

    if "outcome_position" not in st.session_state:
        st.session_state.outcome_position = "Below map"

    st.subheader("LIVE MAP SIMULATION")
    st.session_state.outcome_position = st.radio(
        "Outcome panel position",
        ["Above map", "Below map"],
        index=0 if st.session_state.outcome_position == "Above map" else 1,
        horizontal=True,
    )

    outcome_level, outcome_text = evaluate_round_outcome(state)

    if st.session_state.outcome_position == "Above map":
        if outcome_level == "success":
            st.success(outcome_text)
        elif outcome_level == "warning":
            st.warning(outcome_text)
        elif outcome_level == "critical":
            st.error(outcome_text)
        else:
            st.info(outcome_text)

    map_rows = (
        [{"x": x, "y": y, "entity": "GRASS"} for x, y in state.grass_xy]
        + [{"x": x, "y": y, "entity": "RABBIT"} for x, y in state.rabbits_xy]
        + [{"x": x, "y": y, "entity": "WOLF"} for x, y in state.wolves_xy]
    )
    if map_rows:
        render_icon_map(state)
    else:
        st.info("Map waiting for entities...")

    if st.session_state.outcome_position == "Below map":
        if outcome_level == "success":
            st.success(outcome_text)
        elif outcome_level == "warning":
            st.warning(outcome_text)
        elif outcome_level == "critical":
            st.error(outcome_text)
        else:
            st.info(outcome_text)

    if state.rabbits <= 0:
        st.error("Game result: Team Wolf wins (rabbits reached 0).")
    elif state.wolves <= 0:
        st.success("Game result: Team Rabbit wins (wolves reached 0).")
    elif state.tick >= WIN_MATCH_TICKS:
        if state.rabbit_team_score > state.wolf_team_score:
            st.success(f"Game result: Team Rabbit wins by score at {WIN_MATCH_TICKS} ticks.")
        elif state.wolf_team_score > state.rabbit_team_score:
            st.success(f"Game result: Team Wolf wins by score at {WIN_MATCH_TICKS} ticks.")
        else:
            st.info(f"Game result: Draw at {WIN_MATCH_TICKS} ticks.")


def main() -> None:
    st.set_page_config(page_title="Live Population Simulator", layout="wide")
    init_db()

    mode = st.query_params.get("mode", "sim")
    if mode == "vote":
        render_vote_page()
        return

    st.markdown(
        """
        <style>
            section[data-testid="stSidebar"] button[kind="primary"] { background-color: #16a34a; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.sidebar.header("ตั้งค่าเริ่มต้น")
    if "initial_grass" not in st.session_state:
        st.session_state.initial_grass, st.session_state.initial_rabbits, st.session_state.initial_wolves = (
            PRESET_SCENARIOS["สมดุล (แนะนำ)"]
        )

    selected_preset = st.sidebar.selectbox("รูปแบบสถานการณ์", list(PRESET_SCENARIOS.keys()))
    if st.sidebar.button("ใช้ค่าตั้งต้นจากสถานการณ์", width="stretch"):
        preset_grass, preset_rabbits, preset_wolves = PRESET_SCENARIOS[selected_preset]
        st.session_state.initial_grass = preset_grass
        st.session_state.initial_rabbits = preset_rabbits
        st.session_state.initial_wolves = preset_wolves

    initial_grass = st.sidebar.slider("หญ้าเริ่มต้น", 20, MAX_CELLS, key="initial_grass")
    initial_rabbits = st.sidebar.slider("กระต่ายเริ่มต้น", 5, 160, key="initial_rabbits")
    initial_wolves = st.sidebar.slider("หมาป่าเริ่มต้น", 2, 80, key="initial_wolves")

    if "sim" not in st.session_state:
        st.session_state.sim = initialize_simulation(initial_grass, initial_rabbits, initial_wolves)

    if st.sidebar.button("เริ่มการจำลอง", type="primary", width="stretch"):
        st.session_state.sim = initialize_simulation(initial_grass, initial_rabbits, initial_wolves)
        reset_votes()
        st.session_state.sim.running = True

    st.sidebar.subheader("SIMULATION CONTROLS")
    control_cols = st.sidebar.columns(3)
    if control_cols[0].button("Resume", width="stretch"):
        st.session_state.sim.running = True
    if control_cols[1].button("Pause", width="stretch"):
        st.session_state.sim.running = False
    if control_cols[2].button("Reset", width="stretch"):
        st.session_state.sim = initialize_simulation(initial_grass, initial_rabbits, initial_wolves)
        reset_votes()
        st.session_state.sim.running = False

    st.sidebar.markdown("---")
    st.sidebar.subheader("เหตุการณ์และภัยพิบัติ")
    with st.sidebar.expander("คำอธิบายแต่ละเหตุการณ์", expanded=False):
        for action in ["FOREST FIRE", "DROUGHT", "VACCINE DRIVE", "MIGRATE IN PREY"]:
            st.markdown(f"- **{ACTION_LABELS[action]}**: {ACTION_DESCRIPTIONS[action].split(': ', 1)[1]}")
    for action in ["FOREST FIRE", "DROUGHT", "VACCINE DRIVE", "MIGRATE IN PREY"]:
        if st.sidebar.button(ACTION_LABELS[action], width="stretch"):
            apply_disaster_or_action(st.session_state.sim, action)

    st.sidebar.markdown("---")
    st.sidebar.subheader("QR VOTE")
    base_url = st.sidebar.text_input(
        "App URL for User",
        "https://orthoscopic-kaysen-unexplainable.ngrok-free.dev",
    )
    vote_url = f"{base_url.rstrip('/')}/?mode=vote"
    st.sidebar.caption("Users open this link to vote:")
    st.sidebar.code(vote_url)
    st.sidebar.image(make_qr_image(vote_url), caption="Scan to vote", width="stretch")
    st.sidebar.caption(f"Status: {'RUNNING' if st.session_state.sim.running else 'PAUSED'}")

    rabbit_votes, wolf_votes, total_votes, rabbit_pct, wolf_pct = get_vote_stats()
    render_dashboard(
        st.session_state.sim,
        rabbit_votes,
        wolf_votes,
        total_votes,
        rabbit_pct,
        wolf_pct,
    )

    if st.session_state.sim.running:
        run_tick(st.session_state.sim, rabbit_votes, wolf_votes, total_votes)
        time.sleep(TICK_SECONDS)
        st.rerun()


if __name__ == "__main__":
    main()
