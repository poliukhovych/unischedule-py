import collections
from ortools.sat.python import cp_model
from src.schemas import request as schemas_request
from src.schemas import response as schemas_response


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

    def solve(self, base: list = None, masks: list = None) -> schemas_response.JobResult:
        self._create_variables()
        self._add_hard_constraints()
        self._add_soft_constraints_objective()
        if base or masks:
            self._apply_masks(base, masks)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.params.timeLimitSec
        solver.parameters.random_seed = self.params.seed

        status = solver.Solve(self.model)

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return self._process_results(solver, status)
        else:
            return schemas_response.JobResult(
                assignments=[],
                objective=-1,
                status="infeasible",
                violations=[],
                stats=schemas_response.Stats(
                    solve_time_sec=solver.WallTime(),
                    status=solver.StatusName(status)
                )
            )

    def _create_variables(self):
        for c in self.instance.courses:
            for r in self.instance.rooms:
                for ts in self.instance.timeslots:
                    var_name = f"assign_{c.id}_{r.id}_{ts}"
                    self.assignments[(c.id, r.id, ts)] = self.model.NewBoolVar(var_name)

    def _add_hard_constraints(self):
        for c in self.instance.courses:
            self.model.Add(sum(self.assignments[(c.id, r.id, ts)] for r in self.instance.rooms for ts in
                               self.instance.timeslots) == c.countPerWeek)
        for ts in self.instance.timeslots:
            for r in self.instance.rooms:
                self.model.AddAtMostOne(self.assignments[(c.id, r.id, ts)] for c in self.instance.courses)
            for t in self.instance.teachers:
                courses_for_teacher = [c for c in self.instance.courses if c.teacherId == t.id]
                self.model.AddAtMostOne(
                    [self.assignments[(c.id, r.id, ts)] for c in courses_for_teacher for r in self.instance.rooms])
            for g in self.instance.groups:
                courses_for_group = [c for c in self.instance.courses if any(
                    self.group_to_main_group.get(gid) == self.group_to_main_group.get(g.id) for gid in c.groupIds)]
                self.model.AddAtMostOne(
                    [self.assignments[(c.id, r.id, ts)] for c in courses_for_group for r in self.instance.rooms])
        for c in self.instance.courses:
            total_size = sum(self.groups_map[gid].size for gid in c.groupIds)
            for r in self.instance.rooms:
                if r.capacity < total_size:
                    for ts in self.instance.timeslots:
                        self.model.Add(self.assignments[(c.id, r.id, ts)] == 0)
        for t in self.instance.teachers:
            unavailable_slots = set(self.instance.timeslots) - set(t.available)
            for c in self.instance.courses:
                if c.teacherId == t.id:
                    for ts in unavailable_slots:
                        for r in self.instance.rooms:
                            self.model.Add(self.assignments[(c.id, r.id, ts)] == 0)
        for g in self.instance.groups:
            if g.unavailable:
                for c in self.instance.courses:
                    if g.id in c.groupIds:
                        for ts in g.unavailable:
                            if ts in self.instance.timeslots:
                                for r in self.instance.rooms:
                                    self.model.Add(self.assignments[(c.id, r.id, ts)] == 0)
        for c in self.instance.courses:
            if c.frequency != "weekly":
                allowed_weeks = ["even", "all"] if c.frequency == "even" else ["odd", "all"]
                for ts in self.instance.timeslots:
                    _, week, _ = ts.split('.')
                    if week not in allowed_weeks:
                        for r in self.instance.rooms:
                            self.model.Add(self.assignments[(c.id, r.id, ts)] == 0)

    def _add_soft_constraints_objective(self):
        soft_constraints = []
        weights = self.instance.policy.soft_weights
        if weights.teacher_avoid_slots_penalty > 0:
            for t in self.instance.teachers:
                if t.prefs and t.prefs.avoid_slots:
                    for c in self.instance.courses:
                        if c.teacherId == t.id:
                            for ts in t.prefs.avoid_slots:
                                if ts in self.instance.timeslots:
                                    for r in self.instance.rooms:
                                        soft_constraints.append(
                                            self.assignments[(c.id, r.id, ts)] * weights.teacher_avoid_slots_penalty)
        if weights.teacher_preferred_days_penalty > 0:
            for t in self.instance.teachers:
                if t.prefs and t.prefs.preferred_days:
                    non_preferred_days = {ts.split('.')[0] for ts in self.instance.timeslots} - set(
                        t.prefs.preferred_days)
                    for c in self.instance.courses:
                        if c.teacherId == t.id:
                            for day in non_preferred_days:
                                for week in ["even", "odd", "all"]:
                                    for ts in self.parsed_timeslots.get((day, week), []):
                                        for r in self.instance.rooms:
                                            soft_constraints.append(self.assignments[(c.id, r.id,
                                                                                      ts)] * weights.teacher_preferred_days_penalty)
        if weights.windows_penalty > 0:
            for g in self.instance.groups:
                if not g.parentGroupId:
                    for day in {ts.split('.')[0] for ts in self.instance.timeslots}:
                        for week in ["even", "odd", "all"]:
                            slots_for_day = sorted(
                                [ts for ts in self.instance.timeslots if ts.startswith(f"{day}.{week}.")],
                                key=lambda x: int(x.split('.')[2]))
                            if len(slots_for_day) > 2:
                                for i in range(len(slots_for_day) - 2):
                                    s1, s2, s3 = slots_for_day[i], slots_for_day[i + 1], slots_for_day[i + 2]
                                    class_at_s1, no_class_at_s2, class_at_s3, window = (
                                        self.model.NewBoolVar(f"class_at_{g.id}_{s1}"),
                                        self.model.NewBoolVar(f"no_class_at_{g.id}_{s2}"),
                                        self.model.NewBoolVar(f"class_at_{g.id}_{s3}"),
                                        self.model.NewBoolVar(f"window_{g.id}_{s2}"))
                                    self.model.Add(sum(
                                        self.assignments[(c.id, r.id, s1)] for c in self.instance.courses if
                                        g.id in c.groupIds for r in self.instance.rooms) > 0).OnlyEnforceIf(class_at_s1)
                                    self.model.Add(sum(
                                        self.assignments[(c.id, r.id, s1)] for c in self.instance.courses if
                                        g.id in c.groupIds for r in self.instance.rooms) == 0).OnlyEnforceIf(
                                        class_at_s1.Not())
                                    self.model.Add(sum(
                                        self.assignments[(c.id, r.id, s2)] for c in self.instance.courses if
                                        g.id in c.groupIds for r in self.instance.rooms) == 0).OnlyEnforceIf(
                                        no_class_at_s2)
                                    self.model.Add(sum(
                                        self.assignments[(c.id, r.id, s2)] for c in self.instance.courses if
                                        g.id in c.groupIds for r in self.instance.rooms) > 0).OnlyEnforceIf(
                                        no_class_at_s2.Not())
                                    self.model.Add(sum(
                                        self.assignments[(c.id, r.id, s3)] for c in self.instance.courses if
                                        g.id in c.groupIds for r in self.instance.rooms) > 0).OnlyEnforceIf(class_at_s3)
                                    self.model.Add(sum(
                                        self.assignments[(c.id, r.id, s3)] for c in self.instance.courses if
                                        g.id in c.groupIds for r in self.instance.rooms) == 0).OnlyEnforceIf(
                                        class_at_s3.Not())
                                    self.model.AddBoolAnd([class_at_s1, no_class_at_s2, class_at_s3]).OnlyEnforceIf(
                                        window)
                                    soft_constraints.append(window * weights.windows_penalty)
        if weights.daily_load_balance > 0:
            days = sorted(list({ts.split('.')[0] for ts in self.instance.timeslots}))
            for g in self.instance.groups:
                if not g.parentGroupId:
                    for week in ["even", "odd"]:
                        daily_loads = [sum(
                            self.assignments[(c.id, r.id, ts)] for c in self.instance.courses if g.id in c.groupIds for
                            r in self.instance.rooms for ts in
                            self.parsed_timeslots.get((day, week), []) + self.parsed_timeslots.get((day, 'all'), []))
                                       for day in days]
                        if len(daily_loads) > 1:
                            max_load = self.model.NewIntVar(0, len(self.instance.courses), f"max_load_{g.id}_{week}")
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

    def _process_results(self, solver: cp_model.CpSolver, status: int) -> schemas_response.JobResult:
        final_assignments = []
        for (c_id, r_id, ts), var in self.assignments.items():
            if solver.Value(var) == 1:
                course = self.courses_map[c_id]
                final_assignments.append(
                    schemas_response.Assignment(courseId=c_id, teacherId=course.teacherId, roomId=r_id, timeslot=ts,
                                                groupIds=course.groupIds))
        return schemas_response.JobResult(
            assignments=final_assignments,
            objective=int(solver.ObjectiveValue()),
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

