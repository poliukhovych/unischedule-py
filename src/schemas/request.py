from typing import List, Optional
from pydantic import BaseModel, Field

# Upper bounds to keep a single request from exhausting the solver (CPU/memory)
MAX_TIME_LIMIT_SEC = 300
MAX_ITEMS = 5000


class TeacherPrefs(BaseModel):
    avoid_slots: Optional[List[str]] = Field(default_factory=list, description="Timeslots the teacher wishes to avoid.")
    preferred_days: Optional[List[str]] = Field(default_factory=list,
                                                description="Days the teacher prefers to work on.")


class Teacher(BaseModel):
    id: str
    name: str
    available: List[str] = Field(default_factory=list, description="List of timeslots when the teacher is available.")
    prefs: Optional[TeacherPrefs] = None


class Group(BaseModel):
    id: str
    name: str
    size: int = Field(ge=0)
    parentGroupId: Optional[str] = Field(default=None,
                                         description="If this is a subgroup, specifies the ID of the parent group.")
    subgroups: Optional[List[str]] = Field(default_factory=list,
                                           description="List of subgroup IDs belonging to this group.")
    unavailable: Optional[List[str]] = Field(default_factory=list,
                                             description="List of timeslots when the group cannot have classes (e.g., self-study day).")


class Room(BaseModel):
    id: str
    name: str
    capacity: int = Field(ge=0)


class Course(BaseModel):
    id: str
    name: str
    groupIds: List[str] = Field(
        description="List of group IDs taking this course. Can be one for a regular class or multiple for a stream.")
    teacherId: str
    countPerWeek: int = Field(ge=0, le=50)
    frequency: str = Field(default="weekly", description="Frequency of the course: 'weekly', 'even', or 'odd'.")


class SoftWeights(BaseModel):
    daily_load_balance: int = Field(default=0,
                                    description="Penalty for uneven distribution of classes for a group throughout the week.")
    windows_penalty: int = Field(default=0,
                                 description="Penalty for having empty slots (windows) between classes for a group.")
    teacher_avoid_slots_penalty: int = Field(default=0,
                                             description="Penalty for assigning a teacher to a slot they wish to avoid.")
    teacher_preferred_days_penalty: int = Field(default=0,
                                                description="Penalty for assigning a teacher on a day that is not preferred.")


class Policy(BaseModel):
    soft_weights: SoftWeights


class Instance(BaseModel):
    teachers: List[Teacher] = Field(max_length=MAX_ITEMS)
    groups: List[Group] = Field(max_length=MAX_ITEMS)
    rooms: List[Room] = Field(max_length=MAX_ITEMS)
    courses: List[Course] = Field(max_length=MAX_ITEMS)
    timeslots: List[str] = Field(max_length=MAX_ITEMS)
    policy: Policy


class Params(BaseModel):
    solver: Optional[str] = Field(default="CP_SAT", description="The solver to use. Currently only supports CP_SAT.")
    timeLimitSec: int = Field(ge=1, le=MAX_TIME_LIMIT_SEC)
    seed: Optional[int] = Field(default=42, description="Random seed for the solver.")
    repairLocalSearch: Optional[bool] = Field(default=True, description="Whether to apply local search heuristics.")


class SolveRequest(BaseModel):
    instance: Instance
    params: Params


class FocusAssignment(BaseModel):
    courseId: str
    timeslot: str
    roomId: str


class ExplainRequest(BaseModel):
    instance: Instance
    params: Params
    focus_assignment: FocusAssignment = Field(description="The specific assignment to diagnose for conflicts.")
    base: Optional[List['BaseAssignment']] = Field(default_factory=list,
                                                   description="A list of pre-existing assignments to consider as fixed.")


class BaseAssignment(BaseModel):
    courseId: str
    teacherId: str
    roomId: str
    timeslot: str
    groupIds: List[str]


class Mask(BaseModel):
    courses: Optional[List[str]] = None
    times: Optional[List[str]] = None
    lock: str # "unpin", "lock_timeslot", "lock_room"


class ReoptimizeRequest(BaseModel):
    instance: Instance
    params: Params
    base: List[BaseAssignment] = Field(max_length=MAX_ITEMS)
    masks: Optional[List[Mask]] = Field(default_factory=list, max_length=MAX_ITEMS)

