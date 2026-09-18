# Licenses and attribution

The operator of the Mini is responsible for complying with model and data licenses. This is not legal advice.

## Models (v1)

| Artifact | License (verify on the card before production) | Link |
| --- | --- | --- |
| FLUX.1-schnell | Apache 2.0 | https://huggingface.co/black-forest-labs/FLUX.1-schnell |
| gpt-oss 20B | Apache 2.0 | https://ollama.com/library/gpt-oss |
| Qwen3.5 9B | Check the Ollama/HF model card (often Apache 2.0) | https://ollama.com/library/qwen3.5 |
| nomic-embed-text | Apache 2.0 | https://ollama.com/library/nomic-embed-text |
| Llama 3.2 3B | Llama community license | https://ollama.com/library/llama3.2 |
| Whisper (OpenAI) | MIT | mlx-community weights on Hugging Face |

Do not assume a fine-tune or GGUF requant inherits rights you have not read.

## Map data

- OpenStreetMap / Nominatim / Overpass: https://www.openstreetmap.org/copyright
- Displaying map tiles requires OSM attribution. Geocoding results in JSON still deserve “© OpenStreetMap contributors” in product UI.
- Nominatim usage policy: https://operations.osmfoundation.org/policies/nominatim/
- Do not use Google Places results unless you have a Google key and accept Google’s ToS (`tools.google_places` scope).

## Libraries

Python/JS packages keep their own licenses (BSD/MIT/Apache typically). `ocrmac` / Apple Vision: on-device, no extra model license; still do not use OCR to violate customer confidentiality policies.

## Salesforce customer data

Sending org data to a home Mini is a **data processing** decision. Default `log_prompts=false`. Document Mini location, disk encryption (FileVault **must** be on), and who can SSH to the Mini.
