# HelioDrive Vehicle Command Hub

HelioDrive Vehicle Command Hub is a vehicle control service that maintains the current operational state used by tools for reading and adjusting car functions such as engine, doors, climate, lights, brakes, and driving-related measurements.

## Datastore

### `state.json` — single document
Holds the latest vehicle status snapshot (e.g., power, engine, doors, climate, lights, braking, cruise, destination, and tire pressures) so the service can display and act on the current car state.

- `fuelLevel` — number
- `batteryVoltage` — number
- `engine_state` — string
- `remainingUnlockedDoors` — integer
- `doorStatus` — object
  each record in `doorStatus` has:
  - `driver` — string
  - `passenger` — string
  - `rear_left` — string
  - `rear_right` — string
- `acTemperature` — number
- `fanSpeed` — integer
- `acMode` — string
- `humidityLevel` — number
- `headLightStatus` — string
- `parkingBrakeStatus` — string
- `_parkingBrakeForce` — number
- `_slopeAngle` — number
- `brakePedalStatus` — string
- `_brakePedalForce` — number
- `distanceToNextVehicle` — number
- `cruiseStatus` — string
- `destination` — string
- `frontLeftTirePressure` — number
- `frontRightTirePressure` — number
- `rearLeftTirePressure` — number
- `rearRightTirePressure` — number
- `random_seed` — integer
