"""Put STARK in the Dock where Mimo was (or at the end). Safe to run again."""
import os
import plistlib
import subprocess
import urllib.parse

HOME = os.path.expanduser('~')
DEX = os.path.join(HOME, 'Desktop', 'STARK.app')


def tile_path(tile):
    url = tile.get('tile-data', {}).get('file-data', {}).get('_CFURLString', '')
    return urllib.parse.unquote(url.replace('file://', '')).rstrip('/')


def main():
    raw = subprocess.run(['defaults', 'export', 'com.apple.dock', '-'],
                         capture_output=True, check=True).stdout
    dock = plistlib.loads(raw)
    apps = dock.get('persistent-apps', [])
    kept, slot, has_dex = [], None, False
    for tile in apps:
        name = os.path.basename(tile_path(tile))
        if name in ('Mimo.app', 'Dex.app'):
            slot = len(kept) if slot is None else slot
            continue
        if name == 'STARK.app':
            has_dex = True
        kept.append(tile)
    changed = len(kept) != len(apps)
    if not has_dex:
        url = 'file://' + urllib.parse.quote(DEX) + '/'
        tile = {'tile-type': 'file-tile',
                'tile-data': {'file-label': 'STARK', 'bundle-identifier': 'local.dex.app',
                              'file-data': {'_CFURLString': url, '_CFURLStringType': 15}}}
        kept.insert(slot if slot is not None else len(kept), tile)
        changed = True
    if changed:
        dock['persistent-apps'] = kept
        subprocess.run(['defaults', 'import', 'com.apple.dock', '-'],
                       input=plistlib.dumps(dock, fmt=plistlib.FMT_BINARY), check=True)
        subprocess.run(['killall', 'Dock'], check=False)
        print('Dock updated: STARK' + (' replaced Mimo' if slot is not None else ' added'))
    else:
        print('Dock already has STARK')


if __name__ == '__main__':
    main()
