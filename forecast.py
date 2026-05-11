#!/usr/bin/env python3
import argparse
import configparser
import json
import requests
import sys
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

METRIC_CONFIGS = {
    'daily': {
        'name': 'solar_forecast_watt_hours_day',
        'help': 'Forecasted solar energy production in watt-hours per day',
        'static_labels': {
            'forecast': 'solar'
        },
        'include_coords': False
    },
    'hourly': {
        'name': 'solar_forecast_current_hour_watts',
        'help': 'Forecasted solar power output for the current hour in watts',
        'static_labels': {
            'forecast': 'hourly'
        },
        'include_coords': False
    }
}

class ForecastCache:
    def __init__(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.cache_dir = os.path.join(script_dir, '.cache')
        os.makedirs(self.cache_dir, exist_ok=True)
    
    def _get_cache_key(self, latitude, longitude, declination, azimuth, kwp):
        return f"forecast_{latitude}_{longitude}_{declination}_{azimuth}_{kwp}.json"
    
    def get(self, latitude, longitude, declination, azimuth, kwp, ignore_age=False):
        cache_file = os.path.join(self.cache_dir, self._get_cache_key(
            latitude, longitude, declination, azimuth, kwp))
        
        try:
            if os.path.exists(cache_file):
                with open(cache_file, 'r') as f:
                    cached_data = json.load(f)
                
                if ignore_age:
                    cache_age = time.time() - cached_data['cache_timestamp']
                    print(f"# Using cached data ({int(cache_age/60)} minutes old) due to rate limit", file=sys.stderr)
                    return cached_data['data'], True
                
                if time.time() - cached_data['cache_timestamp'] < 3600:
                    return cached_data['data'], True
        except Exception as e:
            print(f"Cache read error: {e}", file=sys.stderr)
        
        return None, False
    
    def set(self, data, latitude, longitude, declination, azimuth, kwp):
        cache_file = os.path.join(self.cache_dir, self._get_cache_key(
            latitude, longitude, declination, azimuth, kwp))
        
        try:
            cache_data = {
                'cache_timestamp': time.time(),
                'data': data
            }
            with open(cache_file, 'w') as f:
                json.dump(cache_data, f)
        except Exception as e:
            print(f"Cache write error: {e}", file=sys.stderr)

def get_forecast(latitude, longitude, declination, azimuth, kwp, cache):
    cached_data, is_cached = cache.get(latitude, longitude, declination, azimuth, kwp)
    if is_cached:
        return cached_data, True
    
    url = f"https://api.forecast.solar/estimate/{latitude}/{longitude}/{declination}/{azimuth-180}/{kwp}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        
        if response.status_code == 429 or (
            'message' in response.json() and 
            'ratelimit' in response.json()['message'] and 
            response.json()['message']['ratelimit']['remaining'] == 0
        ):
            raise requests.exceptions.RequestException("Rate limit exceeded")
        
        data = response.json()
        cache.set(data, latitude, longitude, declination, azimuth, kwp)
        return data, False
        
    except requests.exceptions.RequestException as e:
        if "Rate limit exceeded" in str(e):
            print(f"# Rate limit exceeded, attempting to use expired cache", file=sys.stderr)
            cached_data, is_cached = cache.get(latitude, longitude, declination, azimuth, kwp, ignore_age=True)
            if is_cached:
                return cached_data, True
            
        print(f"Error fetching forecast data: {e}", file=sys.stderr)
        sys.exit(1)

def get_next_hour_power(data):
    current_time = datetime.now()
    next_hour = (current_time + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    next_hour_str = next_hour.strftime("%Y-%m-%d %H:00:00")
    
    watts = data['result']['watts']
    return watts.get(next_hour_str, 0)

def build_label_string(labels_dict):
    return ','.join([f'{k}="{v}"' for k, v in labels_dict.items() if v is not None])

def output_prometheus_metrics(data, latitude, longitude, shortname=None, show_current_hour=False):
    daily_config = METRIC_CONFIGS['daily']
    print(f"# HELP {daily_config['name']} {daily_config['help']}")
    print(f"# TYPE {daily_config['name']} gauge")
    
    for date, watt_hours in data['result']['watt_hours_day'].items():
        labels = daily_config['static_labels'].copy()
        if daily_config['include_coords']:
            labels.update({
                'latitude': latitude,
                'longitude': longitude
            })
        if shortname:
            labels['shortname'] = shortname
        labels['date'] = date
        
        label_str = build_label_string(labels)
        print(f'{daily_config["name"]}{{{label_str}}} {watt_hours}')
    
    if show_current_hour:
        next_power = get_next_hour_power(data)
        hourly_config = METRIC_CONFIGS['hourly']
        
        print(f"\n# HELP {hourly_config['name']} {hourly_config['help']}")
        print(f"# TYPE {hourly_config['name']} gauge")
        
        labels = hourly_config['static_labels'].copy()
        if hourly_config['include_coords']:
            labels.update({
                'latitude': latitude,
                'longitude': longitude
            })
        if shortname:
            labels['shortname'] = shortname
            
        label_str = build_label_string(labels)
        print(f'{hourly_config["name"]}{{{label_str}}} {next_power}')

def load_config(config_path):
    config = configparser.ConfigParser()
    if os.path.exists(config_path):
        config.read(config_path)
    return config

def main():
    parser = argparse.ArgumentParser(
        description='Solar forecast exporter for Prometheus',
        epilog='Parameters can be set in config.cfg (CLI args take precedence).'
    )
    parser.add_argument('--config', type=str, help='Path to config file (default: config.cfg next to script)')
    parser.add_argument('--latitude', type=float, help='Installation latitude')
    parser.add_argument('--longitude', type=float, help='Installation longitude')
    parser.add_argument('--system-capacity', type=float, help='System capacity in kWp')
    parser.add_argument('--panel-tilt', type=float, help='Panel tilt/declination in degrees')
    parser.add_argument('--panel-azimuth', type=float, help='Panel azimuth in degrees (South = 180)')
    parser.add_argument('--shortname', type=str, help='Optional shortname label for the system')
    parser.add_argument('--show-current-hour', action='store_true', help='Show current hour power forecast')

    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = args.config or os.path.join(script_dir, 'config.cfg')
    config = load_config(config_path)
    section = 'solar'

    def cfg_float(key):
        try:
            return config.getfloat(section, key)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return None

    def cfg_str(key):
        try:
            return config.get(section, key)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return None

    latitude         = args.latitude        or cfg_float('latitude')
    longitude        = args.longitude       or cfg_float('longitude')
    system_capacity  = args.system_capacity or cfg_float('system_capacity')
    panel_tilt       = args.panel_tilt      or cfg_float('panel_tilt')
    panel_azimuth    = args.panel_azimuth   or cfg_float('panel_azimuth')
    shortname        = args.shortname       or cfg_str('shortname')
    show_current_hour = args.show_current_hour or config.getboolean(section, 'show_current_hour', fallback=False)

    missing = [name for name, val in [
        ('--latitude', latitude), ('--longitude', longitude),
        ('--system-capacity', system_capacity), ('--panel-tilt', panel_tilt),
        ('--panel-azimuth', panel_azimuth),
    ] if val is None]
    if missing:
        parser.error(f"Missing required parameters (set via CLI or config.cfg): {', '.join(missing)}")

    cache = ForecastCache()
    forecast_data, is_cached = get_forecast(
        latitude, longitude, panel_tilt, panel_azimuth, system_capacity, cache
    )

    if is_cached:
        print(f"# Using cached data (less than 1 hour old)", file=sys.stderr)

    output_prometheus_metrics(
        forecast_data, latitude, longitude, shortname, show_current_hour
    )

if __name__ == "__main__":
    main()
