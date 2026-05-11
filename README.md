# forecast-solar-exporter

A Prometheus exporter that fetches solar energy production forecasts from the [forecast.solar](https://forecast.solar) public API and exposes them as Prometheus metrics.


## Features

- Daily watt-hour forecasts exposed as a Prometheus gauge with a `date` label
- Optional current-hour watt forecast
- Optional `shortname` label for multi-system setups
- 1-hour response cache to respect the free-tier rate limit (12 req/hour)
- Automatic fallback to expired cache on rate-limit errors

## Requirements

- Python 3.7+
- [requests](https://pypi.org/project/requests/)

```bash
pip install -r requirements.txt
```

## Configuration

### Option 1 — config file (recommended)

Copy the example and fill in your values:

```bash
cp config.cfg.example config.cfg
```

```ini
[solar]
latitude         = 40.000
longitude        = 24.000
system_capacity  = 6.0
panel_tilt       = 15
panel_azimuth    = 180
shortname        = my_roof
show_current_hour = true
```

`config.cfg` is listed in `.gitignore` so your coordinates are never accidentally committed.

Then run with no arguments:

```bash
./forecast.py
```

### Option 2 — CLI flags

```
./forecast.py \
  --latitude 40.000 \
  --longitude 24.000 \
  --system-capacity 6.0 \
  --panel-tilt 15 \
  --panel-azimuth 180 \
  [--shortname my_roof] \
  [--show-current-hour]
```

CLI flags always take precedence over `config.cfg`. You can also point to a different config file:

```bash
./forecast.py --config /etc/solar/site2.cfg
```

### Parameters

| Parameter | CLI flag | Config key | Required | Description |
|---|---|---|---|---|
| Latitude | `--latitude` | `latitude` | Yes | Installation latitude |
| Longitude | `--longitude` | `longitude` | Yes | Installation longitude |
| System capacity | `--system-capacity` | `system_capacity` | Yes | kWp |
| Panel tilt | `--panel-tilt` | `panel_tilt` | Yes | Declination in degrees |
| Panel azimuth | `--panel-azimuth` | `panel_azimuth` | Yes | Degrees (South = 180) |
| Short name | `--shortname` | `shortname` | No | Label added to all metrics |
| Current-hour | `--show-current-hour` | `show_current_hour` | No | Emit hourly watt metric |

## Example output

```
# HELP solar_forecast_watt_hours_day Forecasted solar energy production in watt-hours per day
# TYPE solar_forecast_watt_hours_day gauge
solar_forecast_watt_hours_day{forecast="solar",shortname="my_roof",date="2026-05-11"} 28450
solar_forecast_watt_hours_day{forecast="solar",shortname="my_roof",date="2026-05-12"} 31200
...

# HELP solar_forecast_current_hour_watts Forecasted solar power output for the current hour in watts
# TYPE solar_forecast_current_hour_watts gauge
solar_forecast_current_hour_watts{forecast="hourly",shortname="my_roof"} 2140
```

## Caching

Responses are cached in a `.cache/` directory next to the script, keyed by all system parameters. Cache entries are valid for 1 hour. If the API returns a rate-limit error, the exporter falls back to the most recent cached response (regardless of age) and logs a warning to stderr.

## License

[MIT](LICENSE)
