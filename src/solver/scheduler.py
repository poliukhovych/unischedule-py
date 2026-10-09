import collections
import os
import time
from ortools.sat.python import cp_model
from src.schemas import request as schemas_request
from src.schemas import response as schemas_response

# A weekly class runs every week ("all" slots); odd/even classes only in their own slots.
ALLOWED_WEEKS = {"weekly": ("all",), "odd": ("odd",), "even": ("even",)}

# Each CP-SAT worker keeps its own copy of the model: ~550 MB with 1 worker, ~850 MB with 2,
# ~1 GB with 4 for the seed data. 0 means one worker per CPU.
NUM_WORKERS = int(os.getenv("SOLVER_NUM_WORKERS", "2"))


def expand_every_week(slots) -> set:
    """Availability given as "day.all.N" also covers "day.odd.N" and "day.even.N"."""
    result = set(slots)
    for ts in slots:
        day, week, n = ts.split('.')
        if week == "all":
            result.update((f"{day}.odd.{n}", f"{day}.even.{n}"))
    return result


class ScheduleSolver:
    def __init__(self, instance: schemas_request.Instance, params: schemas_request.Params):
        self.instance = instance
        self.params = params
        self.model = cp_model.CpModel()
        self.assignments = {}
        self._prepare_data_mappings()

    def _prepare_data_mappings(self):
        self.courses_map = {c.id: c for c in self.instance.courses}
        self.teachers_map = {t.id: t for t in self.instance.teachers}
        self.groups_map = {g.id: g for g in self.instance.groups}
        self.rooms_map = {r.id: r for r in self.instance.rooms}
        self.parsed_timeslots = collections.defaultdict(list)
        for ts in self.instance.timeslots:
            day, week, slot_num = ts.split('.')
            self.parsed_timeslots[(day, week)].append(ts)
        self.group_to_main_group = {}
        for group in self.instance.groups:
            if group.parentGroupId:
                self.group_to_main_group[group.id] = group.parentGroupId
            else:
                self.group_to_main_group[group.id] = group.id

        # "day.all.N" happens every week, so it overlaps both "day.odd.N" and "day.even.N";
        # odd and even never overlap. Each set below is a group of slots that can't share a resource.
        by_pair = collections.defaultdict(lambda: collections.defaultdict(list))
        for ts in self.instance.timeslots:
            day, week, slot_num = ts.split('.')
            by_pair[(day, slot_num)][week].append(ts)
        self.overlapping_slot_sets = []
        for weeks in by_pair.values():
            every_week = weeks.get('all', [])
            parts = [weeks[w] for w in ('odd', 'even') if weeks.get(w)]
            for part in parts or [[]]:
                if every_week + part:
                    self.overlapping_slot_sets.append(every_week + part)

    def solve(self, base: list = None, masks: list = None) -> schemas_response.JobResult:
        deadline = time.monotonic() + self.params.timeLimitSec
        self._create_variables()
        self._add_hard_constraints()
        if base or masks:
            self._apply_masks(base, masks)

        # Phase 1: any valid schedule. With the objective attached CP-SAT can spend the whole
        # time limit without finding a single solution on a slow CPU.
        first = self._new_solver(max(1.0, deadline - time.monotonic()))
        status = first.Solve(self.model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return schemas_response.JobResult(
                assignments=[],
                objective=-1,
                status="timeout" if status == cp_model.UNKNOWN else "infeasible",
                violations=[],
                stats=schemas_response.Stats(
                    solve_time_sec=first.WallTime(),
                    status=first.StatusName(status)
                )
            )

        # Phase 2: improve soft constraints from that starting point in the remaining time.
        self._add_soft_constraints_objective()
        remaining = deadline - time.monotonic()
        if remaining >= 1:
            # Hint only the chosen assignments: hinting all ~10^5 vars makes CP-SAT overrun its time limit
            for var in self.assignments.values():
                if first.Value(var):
                    self.model.AddHint(var, 1)
            second = self._new_solver(remaining)
            status2 = second.Solve(self.model)
            if status2 in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                return self._process_results(second, status2)
        # Phase 1 had no objective, so its soft-constraint cost is unknown
        return self._process_results(first, status, objective=-1)

    def _new_solver(self, time_limit: float) -> cp_model.CpSolver:
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit
        solver.parameters.random_seed = self.params.seed
        solver.parameters.num_workers = NUM_WORKERS
        return solver

    def _create_variables(self):
        # Only combinations that can ever be 1 get a variable: the full course x room x slot
        # cross product is ~240k vars for the seed data and needs >1 GB RAM in CP-SAT.
        all_slots = set(self.instance.timeslots)
        self.vars_by_course = collections.defaultdict(list)
        self.vars_by_room_slot = collections.defaultdict(list)
        self.vars_by_teacher_slot = collections.defaultdict(list)
        self.vars_by_main_group_slot = collections.defaultdict(list)
        for c in self.instance.courses:
            teacher = self.teachers_map.get(c.teacherId)
            available = expand_every_week(teacher.available) if teacher else all_slots
            blocked = set()
            for gid in c.groupIds:
                group = self.groups_map.get(gid)
                if group and group.unavailable:
                    blocked.update(expand_every_week(group.unavailable))
            weeks = ALLOWED_WEEKS.get(c.frequency, ("all",))
            slots = [ts for ts in self.instance.timeslots
                     if ts.split('.')[1] in weeks and ts in available and ts not in blocked]
            total_size = sum(self.groups_map[gid].size for gid in c.groupIds)
            rooms = [r for r in self.instance.rooms if r.capacity >= total_size]
            main_groups = {self.group_to_main_group.get(gid) for gid in c.groupIds}
            for r in rooms:
                for ts in slots:
                    var = self.model.NewBoolVar(f"assign_{c.id}_{r.id}_{ts}")
                    self.assignments[(c.id, r.id, ts)] = var
                    self.vars_by_course[c.id].append(var)
                    self.vars_by_room_slot[(r.id, ts)].append(var)
                    self.vars_by_teacher_slot[(c.teacherId, ts)].append(var)
                    for main in main_groups:
                        self.vars_by_main_group_slot[(main, ts)].append(var)

    def _add_hard_constraints(self):
        for c in self.instance.courses:
            course_vars = self.vars_by_course[c.id]
            if course_vars:
                self.model.Add(sum(course_vars) == c.countPerWeek)
            elif c.countPerWeek > 0:
                self.model.AddBoolOr([])  # no room/slot fits this course at all -> infeasible
        teacher_ids = {c.teacherId for c in self.instance.courses}
        main_group_ids = set(self.group_to_main_group.values())
        for slots in self.overlapping_slot_sets:
            for index, keys in ((self.vars_by_room_slot, self.rooms_map.keys()),
                                (self.vars_by_teacher_slot, teacher_ids),
                                (self.vars_by_main_group_slot, main_group_ids)):
                for key in keys:
                    lits = [v for ts in slots for v in index.get((key, ts), [])]
                    if len(lits) > 1:
                        self.model.AddAtMostOne(lits)

    def _add_soft_constraints_objective(self):
        soft_constraints = []
        weights = self.instance.policy.soft_weights
        if weights.teacher_avoid_slots_penalty > 0:
            for t in self.instance.teachers:
                if t.prefs and t.prefs.avoid_slots:
                    for ts in expand_every_week(t.prefs.avoid_slots):
                        for var in self.vars_by_teacher_slot.get((t.id, ts), []):
                            soft_constraints.append(var * weights.teacher_avoid_slots_penalty)
        if weights.teacher_preferred_days_penalty > 0:
            for t in self.instance.teachers:
                if t.prefs and t.prefs.preferred_days:
                    preferred = set(t.prefs.preferred_days)
                    for ts in self.instance.timeslots:
                        if ts.split('.')[0] not in preferred:
                            for var in self.vars_by_teacher_slot.get((t.id, ts), []):
                                soft_constraints.append(var * weights.teacher_preferred_days_penalty)

        if weights.windows_penalty > 0 or weights.daily_load_balance > 0:
            days = sorted({ts.split('.')[0] for ts in self.instance.timeslots})
            pair_nums = sorted({int(ts.split('.')[2]) for ts in self.instance.timeslots})
            main_groups = [g for g in self.instance.groups if not g.parentGroupId]
            for g in main_groups:
                # What the group actually has on an odd / even week: "all" lessons plus that week's ones
                for week in ("odd", "even"):
                    occupied = {}
                    daily_loads = []
                    for day in days:
                        day_vars = []
                        for n in pair_nums:
                            lits = [v for w in ("all", week)
                                    for v in self.vars_by_main_group_slot.get((g.id, f"{day}.{w}.{n}"), [])]
                            day_vars.extend(lits)
                            if lits:
                                busy = self.model.NewBoolVar(f"busy_{g.id}_{week}_{day}_{n}")
                                self.model.AddMaxEquality(busy, lits)
                                occupied[(day, n)] = busy
                        daily_loads.append(sum(day_vars) if day_vars else 0)
                    if weights.windows_penalty > 0:
                        for day in days:
                            for i in range(len(pair_nums) - 2):
                                before = occupied.get((day, pair_nums[i]))
                                gap = occupied.get((day, pair_nums[i + 1]))
                                after = occupied.get((day, pair_nums[i + 2]))
                                if before is None or after is None:
                                    continue
                                window = self.model.NewBoolVar(f"window_{g.id}_{week}_{day}_{pair_nums[i + 1]}")
                                # class before and after with a free pair in between forces window = 1
                                clause = [before.Not(), after.Not(), window]
                                if gap is not None:
                                    clause.append(gap)
                                self.model.AddBoolOr(clause)
                                soft_constraints.append(window * weights.windows_penalty)
                    if weights.daily_load_balance > 0 and len(days) > 1:
                        max_load = self.model.NewIntVar(0, len(pair_nums), f"max_load_{g.id}_{week}")
                        self.model.AddMaxEquality(max_load, daily_loads)
                        soft_constraints.append(max_load * weights.daily_load_balance)
        self.model.Minimize(sum(soft_constraints))

    def _apply_masks(self, base: list, masks: list):
        """
        Applies pinning/unpinning rules. Locks all assignments from 'base'
        except for those explicitly mentioned in 'masks' with an 'unpin' lock type.
        """
        unpinned_courses = set()
        if masks:
            for mask in masks:
                if mask.lock == "unpin" and mask.courses:
                    unpinned_courses.update(mask.courses)

        if base:
            for assignment_model in base:
                course_id = assignment_model.courseId
                if course_id not in unpinned_courses:
                    room_id = assignment_model.roomId
                    timeslot = assignment_model.timeslot
                    key = (course_id, room_id, timeslot)
                    if key in self.assignments:
                        self.model.Add(self.assignments[key] == 1)
                    else:
                        # Pinned into a room/slot the course can never use -> infeasible, not silently moved
                        self.model.AddBoolOr([])

    def _process_results(self, solver: cp_model.CpSolver, status: int, objective: int = None) -> schemas_response.JobResult:
        final_assignments = []
        for (c_id, r_id, ts), var in self.assignments.items():
            if solver.Value(var) == 1:
                course = self.courses_map[c_id]
                final_assignments.append(
                    schemas_response.Assignment(courseId=c_id, teacherId=course.teacherId, roomId=r_id, timeslot=ts,
                                                groupIds=course.groupIds))
        return schemas_response.JobResult(
            assignments=final_assignments,
            objective=int(solver.ObjectiveValue()) if objective is None else objective,
            status="solved",
            violations=[],
            stats=schemas_response.Stats(
                solve_time_sec=round(solver.WallTime(), 2),
                status=solver.StatusName(status)
            )
        )

    def explain_conflict(self, instance_data: schemas_request.Instance, focus: schemas_request.FocusAssignment, base: list) -> schemas_response.ExplainResponse:
        conflicts = []
        course_id, room_id, timeslot = focus.courseId, focus.roomId, focus.timeslot
        course = self.courses_map.get(course_id)
        if not course: return schemas_response.ExplainResponse(conflicts=[f"Course with ID '{course_id}' not found."])
        teacher, room, groups = self.teachers_map.get(course.teacherId), self.rooms_map.get(room_id), [self.groups_map.get(gid) for gid in course.groupIds]
        if timeslot not in teacher.available: conflicts.append(f"Teacher '{teacher.name}' is not available at {timeslot}.")
        for g in groups:
            if g and g.unavailable and timeslot in g.unavailable: conflicts.append(f"Group '{g.name}' is unavailable at {timeslot}.")
        total_size = sum(g.size for g in groups if g)
        if room.capacity < total_size: conflicts.append(f"Room '{room.id}' (capacity: {room.capacity}) is too small for the group(s) (total size: {total_size}).")
        if base:
            for assignment_model in base:
                if assignment_model.timeslot == timeslot:
                    if assignment_model.roomId == room_id: conflicts.append(f"Conflict: Room '{room.id}' is already taken by course '{assignment_model.courseId}' at {timeslot}.")
                    if assignment_model.teacherId == teacher.id: conflicts.append(f"Conflict: Teacher '{teacher.name}' is already teaching course '{assignment_model.courseId}' at {timeslot}.")
                    if not set(assignment_model.groupIds).isdisjoint(set(course.groupIds)): conflicts.append(f"Conflict: At least one group is already assigned to course '{assignment_model.courseId}' at {timeslot}.")
        return schemas_response.ExplainResponse(conflicts=conflicts)

def run_solve_task(instance_dict: dict, params_dict: dict, base: list = None, masks: list = None) -> dict:
    """
    This function is executed by the RQ worker.
    It reconstructs the Pydantic models, runs the solver, and returns the result as a dictionary.
    """
    try:
        instance = schemas_request.Instance.model_validate(instance_dict)
        params = schemas_request.Params.model_validate(params_dict)
        # The queue carries plain dicts; _apply_masks works with the models
        base = [schemas_request.BaseAssignment.model_validate(b) for b in base or []]
        masks = [schemas_request.Mask.model_validate(m) for m in masks or []]

        # Create solver and run it
        solver = ScheduleSolver(instance, params)
        result = solver.solve(base=base, masks=masks)

        # Return the result as a dictionary, so RQ can store it in Redis
        return result.model_dump()
    except Exception as e:
        # If something goes wrong, create an error result
        error_result = schemas_response.JobResult(
            assignments=[],
            objective=-1,
            status="ERROR",
            violations=[str(e)],
            stats=schemas_response.Stats(solve_time_sec=0.0, status="WORKER_ERROR")
        )
        return error_result.model_dump()

