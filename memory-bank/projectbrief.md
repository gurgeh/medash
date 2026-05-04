# Project Brief for DashMe
DashMe is a personal dashboard project for downloading, storing and visualizing health data from various sources. It is for personal use by me, the developer.

A secondary goal is to open the data up to LLMs with a MCP server, to analyze and discuss the data and update my routines accordingly.

Later, I will run some ML models on the data to look for patterns and correlations.

## Data Sources
- Garmin (heart rate, sleep, steps, stress, VO2 max, running, rowing, etc)
- Withings (weight, body composition)
- My own org-mode notes with my journal and resistance training logs.
- Downloaded yearly blood test results
- Nutrition data from my food diary app

## Tech Stack
- The project uses Python for the backend and data processing.
- Frontend will likely be in Svelte or a specialized dashboarding framework.
- Database is SQLite for simplicity.
- Hosting is locally from my laptop. When running the MCP server, it will update the IP for the medash.fendrich.se subdomain on Gandi.