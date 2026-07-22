"""测试基座：加载真实数据文件，提供两人对局的快捷搭建。"""
from __future__ import annotations

import pytest

from ...data_loader import load_library
from .. import engine as E
from ..models import RoomState


@pytest.fixture(scope="session")
def lib():
    return load_library()


class Game:
    """事件溯源测试驱动：act() = decide + 逐事件 apply，并留存完整事件日志。"""

    def __init__(self, lib):
        self.lib = lib
        self.state = RoomState()
        self.events: list[dict] = []

    def act(self, actor_id, action_type, **payload):
        evs = E.decide(self.state, actor_id, action_type, payload, self.lib)
        for ev in evs:
            self.state = E.apply(self.state, ev)
            self.events.append(ev)
        return evs

    def player(self, pid):
        return self.state.players[pid]

    def replay(self):
        return E.replay(self.events)


@pytest.fixture
def game(lib):
    return Game(lib)


@pytest.fixture
def duo(lib):
    """两人局：A=医生(房主)，B=经理，已开局。"""
    g = Game(lib)
    g.act(None, "JOIN", player_id="A", nickname="阿呆", is_host=True)
    g.act(None, "JOIN", player_id="B", nickname="阿瓜")
    g.act("A", "SELECT_PROFESSION", professionId="prof-006")
    g.act("B", "SELECT_PROFESSION", professionId="prof-010")
    g.act("A", "SELECT_DREAM", dreamId="ft-d-safari")
    g.act("B", "SELECT_DREAM", dreamId="ft-d-jet")
    g.act("A", "SET_TURN_ORDER", order=["A", "B"])
    g.act("A", "START_GAME")
    return g
