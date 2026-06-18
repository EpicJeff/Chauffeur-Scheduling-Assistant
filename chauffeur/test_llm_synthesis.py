import json
import urllib.request
import urllib.error
from unittest.mock import patch, MagicMock
from io import BytesIO

# Import target functions
from services.llm import generate_rules_from_philosophy, test_llm_connection, refine_scheduling_text
from models.schemas import Rule, PriorityRule

def test_generate_rules_mock():
    # Mocking Gemini response
    mock_response_data = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps({
                                "rules": [
                                    {
                                        "driver_id": "mom",
                                        "constraint_type": "required",
                                        "keywords": ["soccer"],
                                        "passenger_ids": [],
                                        "days_of_week": [0],
                                        "time_start": "17:00",
                                        "time_end": "19:00"
                                    }
                                ],
                                "priority_rules": [
                                    {
                                        "weight_modifier": 1000,
                                        "keywords": ["critical"],
                                        "passenger_ids": []
                                    }
                                ]
                            })
                        }
                    ]
                }
            }
        ]
    }
    
    mock_response_bytes = json.dumps(mock_response_data).encode('utf-8')
    
    # Mocking urlopen
    mock_urlopen = MagicMock()
    mock_urlopen.status = 200
    mock_urlopen.read.return_value = mock_response_bytes
    mock_urlopen.__enter__.return_value = mock_urlopen

    drivers = [
        {"id": "mom", "name": "Lorena", "group": "primary", "priority_index": 1, "bio": "Lorena always drives Nate to soccer on Mondays."}
    ]
    passengers = [
        {"id": "nate", "name": "Nate", "calendar_ids": ["nate@gmail.com"], "bio": "Nate has soccer on Mondays."}
    ]

    with patch('urllib.request.urlopen', return_value=mock_urlopen):
        rules, priority_rules, raw_log = generate_rules_from_philosophy(
            provider="gemini",
            url="http://localhost:11434",
            api_key="mock_key",
            model="gemini-1.5-flash",
            philosophy="Lorena always drives Nate to soccer on Mondays.",
            drivers=drivers,
            passengers=passengers
        )
        
        print("Generated Rules:", rules)
        print("Generated Priority Rules:", priority_rules)
        
        assert len(rules) == 1
        assert rules[0]["driver_id"] == "mom"
        assert rules[0]["is_ai_generated"] is True
        assert rules[0]["keywords"] == ["soccer"]
        
        assert len(priority_rules) == 1
        assert priority_rules[0]["weight_modifier"] == 1000
        assert priority_rules[0]["is_ai_generated"] is True
        assert priority_rules[0]["keywords"] == ["critical"]
        
        print("LLM Synthesis test completed successfully!")

def test_test_connection_mock():
    # Mock test connection for Gemini
    mock_urlopen = MagicMock()
    mock_urlopen.status = 200
    mock_urlopen.read.return_value = b'{"success": true}'
    mock_urlopen.__enter__.return_value = mock_urlopen

    with patch('urllib.request.urlopen', return_value=mock_urlopen):
        success, message = test_llm_connection(
            provider="gemini",
            api_key="mock_key"
        )
        print("Gemini connection test status:", success, "Message:", message)
        assert success is True

    # Mock test connection for Ollama
    mock_urlopen_ollama = MagicMock()
    mock_urlopen_ollama.read.return_value = json.dumps({
        "models": [{"name": "qwen2.5:7b"}]
    }).encode('utf-8')
    mock_urlopen_ollama.__enter__.return_value = mock_urlopen_ollama

    with patch('urllib.request.urlopen', return_value=mock_urlopen_ollama):
        success, message = test_llm_connection(
            provider="ollama",
            url="http://localhost:11434",
            model="qwen2.5:7b"
        )
        print("Ollama connection test status:", success, "Message:", message)
        assert success is True
        
    print("LLM connection tests completed successfully!")

def test_refine_text_mock():
    mock_response_data = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": "Lorena (Mom) is primary driver for Nate's soccer practices on Mondays."
                        }
                    ]
                }
            }
        ]
    }
    mock_response_bytes = json.dumps(mock_response_data).encode('utf-8')
    
    mock_urlopen = MagicMock()
    mock_urlopen.status = 200
    mock_urlopen.read.return_value = mock_response_bytes
    mock_urlopen.__enter__.return_value = mock_urlopen

    with patch('urllib.request.urlopen', return_value=mock_urlopen):
        refined = refine_scheduling_text(
            provider="gemini",
            url="http://localhost:11434",
            api_key="mock_key",
            model="gemini-1.5-flash",
            text="Mom always drives nate soccer mondays",
            context_type="driver_bio"
        )
        print("Refined Text:", refined)
        assert "Lorena (Mom)" in refined
        
    print("LLM refine text test completed successfully!")

if __name__ == "__main__":
    test_generate_rules_mock()
    test_test_connection_mock()
    test_refine_text_mock()
