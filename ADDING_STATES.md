# Adding New Stove States

If your Aduro stove reports states that are not yet in the integration, you'll see warnings in the Home Assistant logs and sensors will show "Unknown State X".

## How to Add New States

### 1. Check the Logs

Look for warnings like:
```
WARNING: Unknown stove state detected: 99 - Please report this to the integration developer
```

### 2. Identify the State

Note down:
- **State number** (e.g., "99")
- **When it occurs** (e.g., "during startup", "after error")
- **What the stove is doing** (e.g., "cleaning", "cooling down")
- **Substate** (if applicable)

### 3. Update `const.py`

Add the new state to the appropriate mappings:

#### For Main States (STATE_NAMES_DISPLAY):

```python
STATE_NAMES_DISPLAY: Final = {
    "0": "Operating {heatlevel}",
    # ... existing states ...
    "99": "Your New State",  # Add your state here
}
```

#### For Substates (SUBSTATE_NAMES_DISPLAY):

```python
SUBSTATE_NAMES_DISPLAY: Final = {
    "0": "Waiting",
    # ... existing states ...
    "99": "Your New Substate Description",  # Add your substate here
}
```

#### Classify the State:

Add to either STARTUP_STATES or SHUTDOWN_STATES:

```python
# If the stove is running/starting up:
STARTUP_STATES: Final = ["0", "2", "4", "5", "32", "99"]  # Add "99"

# OR if the stove is stopped/off:
SHUTDOWN_STATES: Final = ["6", "9", "13", "14", "20", "28", "34", "99"]  # Add "99"
```

### 4. Update Translations

#### In `translations/en.json`:

```json
"state": {
  "name": "State",
  "state": {
    "state_operating": "Operating {heatlevel}",
    "state_new_state": "Your New State Description"
  }
}
```

#### In `translations/sv.json`:

```json
"state": {
  "name": "Tillstånd",
  "state": {
    "state_operating": "Drift {heatlevel}",
    "state_new_state": "Din Nya Statusbeskrivning"
  }
}
```

### 5. Update STATE_NAMES (for translations):

```python
STATE_NAMES: Final = {
    "0": "state_operating",
    # ... existing states ...
    "99": "state_new_state",  # Add translation key
}
```

## Example: Adding State "99" (Maintenance Mode)

### 1. Update `const.py`:

```python
# Add to display names
STATE_NAMES_DISPLAY: Final = {
    # ... existing ...
    "99": "Maintenance",
}

SUBSTATE_NAMES_DISPLAY: Final = {
    # ... existing ...
    "99": "Performing maintenance cycle",
}

# Add to classification (it's not running, so SHUTDOWN)
SHUTDOWN_STATES: Final = ["6", "9", "13", "14", "20", "28", "34", "99"]

# Add translation key
STATE_NAMES: Final = {
    # ... existing ...
    "99": "state_maintenance",
}

SUBSTATE_NAMES: Final = {
    # ... existing ...
    "99": "substate_maintenance_cycle",
}
```

### 2. Update `translations/en.json`:

```json
"state": {
  "state": {
    "state_maintenance": "Maintenance"
  }
},
"substate": {
  "state": {
    "substate_maintenance_cycle": "Performing maintenance cycle"
  }
}
```

### 3. Update `translations/sv.json`:

```json
"state": {
  "state": {
    "state_maintenance": "Underhåll"
  }
},
"substate": {
  "state": {
    "substate_maintenance_cycle": "Utför underhållscykel"
  }
}
```

### 4. Restart Home Assistant

The new state will now be recognized!

## Reporting Unknown States

If you encounter unknown states, please report them by creating a GitHub issue with:

1. **State number** (from the log warning)
2. **Substate number** (if shown)
3. **When it occurred** (startup, shutdown, during operation, etc.)
4. **Stove model** (H1, H2, H3, or H4)
5. **What the stove was doing** (visual observation)
6. **Any relevant logs** (copy from Home Assistant logs)

This helps improve the integration for everyone!

## State Classification Guide

**STARTUP_STATES** - Stove is running or starting:
- Ignition phases
- Normal operation
- Heating up
- Any active combustion

**SHUTDOWN_STATES** - Stove is stopped or stopping:
- Off/standby
- Temperature reached (stopped automatically)
- Error states
- Manual stop
- Cooldown phases

**Neither** - Only for truly unknown states (logs warning)

## Testing

After adding a new state:

1. Restart Home Assistant
2. Wait for stove to enter the new state
3. Check that sensors show the correct text
4. Verify switch (power) shows correct state (on/off)
5. Check that translations work (change language in profile)
6. Monitor logs for any remaining warnings
