from typing import Literal, Optional

from pydantic import BaseModel


class LeaderboardEntry(BaseModel):
    rank: int
    rank_label: str
    user_id: int
    display_name: str
    subtext: str
    xp_this_week: int
    xp_last_week: int
    display_change: str
    change_type: Literal["percentage", "absolute"]
    current_level: int
    level_label: str
    is_current_user: bool


class WeeklyLeaderboardResponse(BaseModel):
    week_start: str
    week_end: str
    leaderboard: list[LeaderboardEntry]
    your_position: Optional[LeaderboardEntry] = None
