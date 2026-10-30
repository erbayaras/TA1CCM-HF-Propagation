#!/usr/bin/env python3
"""Fetch observed NOAA SWPC HF space weather values; never fabricate measurements."""
import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
BASE = 'https://services.swpc.noaa.gov'

def fetch(path):
    req = Request(BASE + path, headers={'User-Agent': 'TA1CCM-HF-Propagation/1.0'})
    with urlopen(req, timeout=30) as response:
        return json.load(response)

def latest(rows, field, timefield='time_tag'):
    valid = [r for r in rows if isinstance(r, dict) and r.get(field) is not None and r.get(timefield)]
    if not valid:
        raise ValueError('No valid data for ' + field)
    return max(valid, key=lambda r: r[timefield])

def xray_class(flux):
    flux = float(flux)
    if not math.isfinite(flux) or flux <= 0:
        raise ValueError('Invalid X-ray flux')
    for label, base in [('X', 1e-4), ('M', 1e-5), ('C', 1e-6), ('B', 1e-7)]:
        if flux >= base:
            return f'{label}{flux / base:.1f}'
    return f'A{flux / 1e-8:.1f}'

now = datetime.now(timezone.utc)
output = {'sfi': None, 'kp': None, 'a': None, 'xray': None,
          'updated_utc': now.strftime('%Y-%m-%d %H:%M UTC'), 'observations': {}, 'errors': []}

try:
    flux = latest(fetch('/products/10cm-flux-30-day.json'), 'flux')
    output['sfi'] = round(float(flux['flux']))
    output['observations']['sfi'] = flux['time_tag'] + ' UTC'
except Exception as exc:
    output['errors'].append('SFI: ' + str(exc))

try:
    rows = fetch('/products/noaa-planetary-k-index.json')
    kp = latest(rows, 'Kp')
    output['kp'] = round(float(kp['Kp']), 2)
    output['observations']['kp'] = kp['time_tag'] + ' UTC'
    # A is a mean of eight 3-hour linear a indices from the last *completed* UTC day.
    # NOAA a_running is a 3-hour index, not the daily A index itself.
    day = (now - timedelta(days=1)).strftime('%Y-%m-%d')
    day_rows = [r for r in rows if str(r.get('time_tag', '')).startswith(day) and r.get('a_running') is not None]
    if len(day_rows) == 8:
        output['a'] = round(sum(float(r['a_running']) for r in day_rows) / 8)
        output['observations']['a'] = day + ' UTC (derived from 8 three-hour a indices)'
    else:
        output['errors'].append('A: complete prior UTC day unavailable')
except Exception as exc:
    output['errors'].append('Kp/A: ' + str(exc))

try:
    rows = fetch('/json/goes/primary/xrays-6-hour.json')
    valid = [r for r in rows if isinstance(r, dict) and r.get('energy') == '0.1-0.8nm'
             and r.get('flux') is not None and float(r['flux']) > 0 and r.get('time_tag')]
    if not valid:
        raise ValueError('No valid 0.1-0.8 nm readings')
    latest_x = max(valid, key=lambda r: r['time_tag'])
    output['xray'] = xray_class(latest_x['flux'])
    output['observations']['xray'] = latest_x['time_tag'] + ' UTC'
except Exception as exc:
    output['errors'].append('X-ray: ' + str(exc))

# If NOAA temporarily fails, retain the last successful measurements rather than erase them.
path = ROOT / 'stats.json'
if path.exists():
    try:
        previous = json.loads(path.read_text(encoding='utf-8'))
        for key in ('sfi', 'kp', 'a', 'xray'):
            if output[key] is None and previous.get(key) is not None:
                output[key] = previous[key]
                if key in previous.get('observations', {}):
                    output['observations'][key] = previous['observations'][key]
    except (ValueError, OSError):
        pass

path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(output, indent=2))
