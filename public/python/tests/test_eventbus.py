import pytest
from public.python.engine import EventBus

def test_event_bus():
    bus = EventBus()
    
    events_received = []
    
    def on_event(payload):
        events_received.append(payload)
        
    bus.subscribe("TEST_TOPIC", on_event)
    
    bus.publish("TEST_TOPIC", {"data": "test1"})
    bus.publish("TEST_TOPIC", {"data": "test2"})
    bus.publish("OTHER_TOPIC", {"data": "test3"})
    
    assert len(events_received) == 2
    assert events_received[0]["data"] == "test1"
    assert events_received[1]["data"] == "test2"
