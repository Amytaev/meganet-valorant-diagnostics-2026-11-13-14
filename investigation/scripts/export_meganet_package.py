"""Export a reviewed technical directory as portable HTML and a checksummed ZIP."""
import argparse
import hashlib
import re
import shutil
import zipfile
from pathlib import Path
from urllib.parse import unquote
from export_final_html import render


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package',type=Path)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args(); p=args.package.resolve(); output=args.output_dir.resolve()
    if output.is_relative_to(p):
        parser.error('Output directory must be outside source package.')
    html=render(p/'README.md')
    for kind in ['blob','tree']:
        prefix=f'https://github.com/Amytaev/meganet-valorant-diagnostics-2026-11-13-14/{kind}/main/investigation/{p.name}/'
        html=html.replace(prefix,'')
    html=html.replace('Meganet × Valorant — итог расследования','Meganet — Valorant / CS2: технический пакет')
    digest=hashlib.sha256((p/'README.md').read_bytes()).hexdigest()
    html=re.sub(r'<footer>.*?</footer>',f'<footer>Пакет для владельца; не отправлен провайдеру. SHA-256 README.md: {digest}. Полные исходные выводы находятся в measurements/. Скриптов и внешних медиа нет.</footer>',html,flags=re.S)
    assert '<script' not in html and 'src="http' not in html
    for href in re.findall(r'href="([^"]+)"',html):
        if href.startswith(('http://','https://','#')):
            continue
        target=(p/unquote(href)).resolve()
        assert target.is_relative_to(p) and target.exists(),href
    (p/'README.html').write_text(html,encoding='utf-8',newline='\n')
    manifest=p/'SHA256SUMS.txt'
    files=sorted(f for f in p.rglob('*') if f.is_file() and f!=manifest)
    manifest.write_text(''.join(hashlib.sha256(f.read_bytes()).hexdigest()+'  '+f.relative_to(p).as_posix()+'\n' for f in files),encoding='utf-8',newline='\n')
    output.mkdir(parents=True,exist_ok=True)
    name='Meganet-Technical-Package-2026-11-14'
    destination=output/name
    # Copy only known package files; never delete an output directory.
    for f in [*files,manifest]:
        target=destination/f.relative_to(p)
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(f,target)
        assert hashlib.sha256(target.read_bytes()).digest()==hashlib.sha256(f.read_bytes()).digest()
    archive=output/(name+'.zip')
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for f in [*files,manifest]:
            z.write(f,name+'/'+f.relative_to(p).as_posix())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for f in [*files,manifest]:
            assert hashlib.sha256(z.read(name+'/'+f.relative_to(p).as_posix())).digest()==hashlib.sha256(f.read_bytes()).digest()
    print(f'Exported {len(files)+1} files; archive {archive.stat().st_size} bytes: {archive}')


if __name__=='__main__':
    main()
