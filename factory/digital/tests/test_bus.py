# -*- coding: utf-8 -*-
import pytest

import wqbus
from wqbus import ValidationError


def test_topic_helpers():
    assert wqbus.unit_topic("grd-01", "status") == "wq/gearbox/machining/grd-01/status"
    assert wqbus.unit_topic("qc-01", "measurement") == "wq/gearbox/quality/qc-01/measurement"
    assert wqbus.topic("ai", "briefing") == "wq/gearbox/ai/briefing"
    assert wqbus.split("wq/gearbox/machining/grd-01/cmd/ack") == {
        "area": "machining", "unit": "grd-01", "category": "cmd/ack"}
    assert wqbus.split("wq/gearbox/ai/proposal")["category"] == "proposal"
    assert wqbus.split("wq/gearbox/office/erp/work_order")["unit"] == "erp"
    assert wqbus.qos_for("wq/gearbox/logistics/agv-01/status") == 0
    assert len(wqbus.MACHINES) == 12 and set(wqbus.MACHINES) <= set(wqbus.UNITS)


def test_every_machine_maps_to_a_factory_workstation():
    from factory import data
    for u in wqbus.MACHINES:
        assert wqbus.UNITS[u][3] in data.WORKSTATIONS, u


def test_envelope_ok_and_roundtrip():
    m = wqbus.make("machine.status", "sim/grd-01", {"state": "down", "progress": 0}, corr="WO-1")
    assert m["v"] == 1 and m["ts"].endswith("Z") and m["mode"] == "teach"
    import json
    assert wqbus.parse(json.dumps(m).encode()) == m


@pytest.mark.parametrize("type_,data,msg", [
    ("machine.status", {"state": "busy"}, "state"),
    ("machine.status", {"state": "run", "progress": 1.5}, "progress"),
    ("quality.measurement", {"part_serial": "x"}, "item"),
    ("ai.proposal", {"proposal_id": "p", "action": "a", "preview": {}, "requires_confirm": False}, "requires_confirm"),
])
def test_bad_data_rejected(type_, data, msg):
    with pytest.raises(ValidationError) as e:
        wqbus.make(type_, "t", data)
    assert msg in str(e.value)


def test_unknown_type_and_newer_version_rejected():
    m = wqbus.make("machine.ack", "t", {"accepted": True})
    with pytest.raises(ValidationError):
        wqbus.validate(dict(m, type="machine.teleport"))
    with pytest.raises(ValidationError):
        wqbus.validate(dict(m, v=2))
    with pytest.raises(ValidationError):
        wqbus.validate(dict(m, mode="demo"))


def test_extra_fields_allowed():
    m = wqbus.make("machine.status", "t", {"state": "run", "new_field_from_v1_1": 3})
    assert m["data"]["new_field_from_v1_1"] == 3
