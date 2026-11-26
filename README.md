# Family Race (multiplayer Training Race)
Same race rule as the Training Race tool, but only people (and optional AI horses). No StableKing, no real horses.

## How a game goes
1. One person opens the link, writes a name, presses **Create a new room** and gets a 4-letter code.
2. Friends open the same link, write a name and enter the code (**Join room**).
3. Host picks the distance (5-24 furlongs) and 0-8 AI horses.
4. Everyone writes a secret training: exactly `distance` whole numbers that add up to 100, then presses **Lock in**. Nobody sees other plans until the race.
5. Host presses **Start the race**. The race is shown furlong by furlong; plans are revealed.
6. Host presses **Next round** for new trainings (same people, new distance if wanted).

## Race rule
Per furlong: higher number = better (rank 0), next = 1 point, ... Ties are random (equal speeds, no jockeys, no ground). Lowest total rank points wins; a tie for the win is decided at random and shown.
AI horses use random plans in several styles (flat, levels, spikes, equal share, front/back loaded, blocks).

## Run on your computer
    python3 server.py
Open http://localhost:8000 . Phones on the same wifi: http://<your-mac-ip>:8000 . No libraries needed (Python 3.9+).

## Deploy on Render (free)
1. Put this folder in a GitHub repository (private is fine).
2. Render dashboard -> New -> Web Service -> pick the repo. Render reads `render.yaml` (runtime Python, start command `python3 server.py`, health check `/health`).
3. When it is live, share the https link with the family.
Notes: rooms live in memory only. The free plan sleeps after ~15 minutes without visitors and a restart deletes rooms (the first visit takes ~1 minute to wake up). Rooms close after 6 hours. Max 12 players and 300 rooms.

## Files
- `server.py` race logic, rooms, API (no outside libraries)
- `index.html` the whole page
- `render.yaml`, `.gitignore`, this README
