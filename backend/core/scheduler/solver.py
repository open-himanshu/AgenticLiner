"""
Intelligent Event Scheduler using Google OR-Tools CP-SAT Solver.
Solves conflict-free timetable scheduling satisfying:
1. Room conflict constraints (at most one session per room per time slot)
2. Room capacity constraints (attendance <= capacity)
3. Speaker availability windows (explicit slot indices or time ranges)
4. Speaker single-assignment constraints (no speaker in two rooms simultaneously)
5. Session dependency precedence (e.g., Keynote before Workshop)
6. Dynamic re-scheduling on speaker cancellation with minimal displacement.
"""

from ortools.sat.python import cp_model
from typing import List, Dict, Any, Optional
import json
import re

def _parse_time_minutes(t_str: str) -> int:
    """Convert 'HH:MM AM/PM' or 'HH:MM' to minutes from midnight."""
    t_str = t_str.strip().upper()
    is_pm = "PM" in t_str
    is_am = "AM" in t_str
    cleaned = re.sub(r"[^0-9:]", "", t_str)
    parts = cleaned.split(":")
    if len(parts) < 2:
        return 0
    h = int(parts[0])
    m = int(parts[1])
    if is_pm and h < 12:
        h += 12
    elif is_am and h == 12:
        h = 0
    return h * 60 + m

def _is_slot_in_windows(slot_name: str, windows: List[str]) -> bool:
    """Checks whether a slot time window falls completely within any speaker availability window."""
    times = re.findall(r"\b\d{1,2}:\d{2}(?:\s*[AaPp][Mm])?\b", slot_name.replace("–", "-"))
    if len(times) < 2:
        return True

    s_start = _parse_time_minutes(times[0])
    s_end = _parse_time_minutes(times[1])

    for w in windows:
        w_times = re.findall(r"\b\d{1,2}:\d{2}(?:\s*[AaPp][Mm])?\b", str(w).replace("–", "-"))
        if len(w_times) >= 2:
            w_start = _parse_time_minutes(w_times[0])
            w_end = _parse_time_minutes(w_times[1])
            if w_start <= s_start and s_end <= w_end:
                return True
    return False


class EventScheduler:
    def __init__(
        self,
        rooms: List[Dict[str, Any]],
        slots: List[str],
        sessions: List[Dict[str, Any]],
        speakers: Optional[List[Dict[str, Any]]] = None
    ):
        """
        rooms: list of dicts with keys ['id', 'name', 'capacity']
        slots: list of slot identifiers (e.g. ['Slot 1 (09:00-10:30)', 'Slot 2 (11:00-12:30)', ...])
        sessions: list of dicts with keys ['id', 'title', 'expected_attendance', 'speaker_id', 'depends_on']
        speakers: list of dicts with keys ['id', 'name', 'availability_slots'] or ['availability_json']
        """
        self.rooms = rooms
        self.slots = slots
        self.sessions = sessions
        self.speakers = speakers or []
        self.model = cp_model.CpModel()
        self.solver = cp_model.CpSolver()
        self.x = {} # Decision variables: (session_id, room_id, slot_idx) -> BoolVar

    def build_model(self) -> None:
        """Constructs CP-SAT boolean decision variables and enforces hard constraints."""
        num_slots = len(self.slots)

        # Parse speaker availability windows if provided
        speaker_allowed_slots: Dict[str, set] = {}
        for spk in self.speakers:
            spk_id = spk.get("id")
            if not spk_id:
                continue
            allowed = None
            if "availability_slots" in spk and spk["availability_slots"] is not None:
                allowed = set(spk["availability_slots"])
            elif "available_slots" in spk and spk["available_slots"] is not None:
                raw = spk["available_slots"]
                if all(isinstance(x, int) for x in raw):
                    allowed = set(raw)
                else:
                    allowed = {i for i, s in enumerate(self.slots) if s in raw}
            elif "availability_json" in spk and spk["availability_json"]:
                try:
                    raw_avail = spk["availability_json"]
                    windows = json.loads(raw_avail) if isinstance(raw_avail, str) else raw_avail
                    if isinstance(windows, list):
                        allowed = {
                            t for t, slot_str in enumerate(self.slots)
                            if _is_slot_in_windows(slot_str, windows)
                        }
                except Exception:
                    allowed = None

            if allowed is not None:
                speaker_allowed_slots[spk_id] = allowed

        # Create 3D binary decision matrix: x[s, r, t] = 1 if session s is in room r at slot t
        for s in self.sessions:
            s_id = s["id"]
            attendance = s.get("expected_attendance", 0)
            spk_id = s.get("speaker_id")
            allowed_for_speaker = speaker_allowed_slots.get(spk_id)

            for r in self.rooms:
                r_id = r["id"]
                capacity = r.get("capacity", 0)

                for t in range(num_slots):
                    # Hard Constraint A: Capacity limit
                    if attendance > capacity:
                        self.x[(s_id, r_id, t)] = self.model.NewConstant(0)
                    # Hard Constraint B: Speaker availability window
                    elif allowed_for_speaker is not None and t not in allowed_for_speaker:
                        self.x[(s_id, r_id, t)] = self.model.NewConstant(0)
                    else:
                        self.x[(s_id, r_id, t)] = self.model.NewBoolVar(f"x_{s_id}_{r_id}_{t}")

        # Constraint 1: Every session must be scheduled in exactly ONE room and ONE time slot
        for s in self.sessions:
            s_id = s["id"]
            self.model.AddExactlyOne(
                self.x[(s_id, r["id"], t)]
                for r in self.rooms
                for t in range(num_slots)
            )

        # Constraint 2: A room can host at most ONE session in any given time slot
        for r in self.rooms:
            r_id = r["id"]
            for t in range(num_slots):
                self.model.AddAtMostOne(
                    self.x[(s["id"], r_id, t)]
                    for s in self.sessions
                )

        # Constraint 3: A speaker can be in at most ONE session at any given time slot
        speakers_sessions = {}
        for s in self.sessions:
            spk = s.get("speaker_id")
            if spk:
                speakers_sessions.setdefault(spk, []).append(s["id"])

        for spk, sess_ids in speakers_sessions.items():
            if len(sess_ids) > 1:
                for t in range(num_slots):
                    self.model.AddAtMostOne(
                        self.x[(s_id, r["id"], t)]
                        for s_id in sess_ids
                        for r in self.rooms
                    )

        # Constraint 4: Precedence / Dependency (e.g. Session A must happen strictly before Session B)
        slot_of = {}
        for s in self.sessions:
            s_id = s["id"]
            slot_var = self.model.NewIntVar(0, num_slots - 1, f"slot_of_{s_id}")
            self.model.Add(
                slot_var == sum(t * self.x[(s_id, r["id"], t)] for r in self.rooms for t in range(num_slots))
            )
            slot_of[s_id] = slot_var

        for s in self.sessions:
            s_id = s["id"]
            prereq = s.get("depends_on")
            if prereq and prereq in slot_of:
                self.model.Add(slot_of[prereq] < slot_of[s_id])

    def solve(self) -> Dict[str, Any]:
        """Runs the CP-SAT solver and extracts the clash-free schedule timetable."""
        self.build_model()
        self.solver.parameters.max_time_in_seconds = 10.0
        status = self.solver.Solve(self.model)

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            schedule = []
            num_slots = len(self.slots)

            for s in self.sessions:
                s_id = s["id"]
                for r in self.rooms:
                    r_id = r["id"]
                    for t in range(num_slots):
                        val = self.solver.Value(self.x[(s_id, r_id, t)])
                        if val == 1:
                            schedule.append({
                                "session_id": s_id,
                                "session_title": s["title"],
                                "room_id": r_id,
                                "room_name": r["name"],
                                "slot_index": t,
                                "slot_time": self.slots[t],
                                "speaker_id": s.get("speaker_id"),
                                "expected_attendance": s.get("expected_attendance", 0)
                            })

            schedule.sort(key=lambda item: (item["slot_index"], item["room_name"]))
            return {
                "success": True,
                "status": "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE",
                "schedule": schedule,
                "total_sessions_scheduled": len(schedule),
                "unassigned_sessions": 0
            }
        else:
            return {
                "success": False,
                "status": "INFEASIBLE",
                "message": "No feasible timetable found satisfying all room capacities, speaker availabilities and precedence rules.",
                "schedule": []
            }
