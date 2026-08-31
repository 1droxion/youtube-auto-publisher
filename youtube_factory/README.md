# YouTube Factory V1

Isolated Funny Reaction long-video factory. This module does not modify the existing `pipeline.py` auto-publisher flow.

## Milestone 1

Implemented:

- project model
- processing job model
- persistent JSON development store
- project creation
- dashboard project list
- canonical processing statuses
- API endpoint for projects

## Run locally

From the repository root:

```bash
python -m youtube_factory.server
```

Open:

```text
http://127.0.0.1:8787
```

## Next milestone

Add source-video and reaction-video uploads into project-scoped asset folders. Then normalize both inputs with FFmpeg without changing the original files.

## Architecture rule

Every expensive stage will persist its output so failures can be retried independently. The JSON store used for the first development milestone is hidden behind `JsonStore`; it can be replaced by Supabase/Postgres without changing the media pipeline contract.
