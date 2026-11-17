#!/bin/zsh
# One command to rebuild everything for the hand-in:
#   1. regenerate the dummy dataset (data/*.csv + data.js)
#   2. bundle the offline single-file dashboard
#   3. syntax-check the dashboard script
#   5. print the one-page note to PDF and package the hand-in zip in dist/
#   4. screenshot every page (light + dark) into screenshots/ and check each page renders without script errors
set -e
cd "${0:A:h}"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

echo "1/5 data";       python3 generate_data.py
echo "2/5 bundle";     python3 build_standalone.py
echo "3/5 check";      python3 -c "
s=open('dashboard.html').read(); i=s.index('<script>\n(()'); open('.app.check.js','w').write(s[i+8:s.rindex('</script>')])"
node --check .app.check.js && rm .app.check.js && echo "   script OK"

echo "4/5 screenshots + render check"
mkdir -p screenshots
FILE="file://$PWD/Dealer_Receivables_Watch.html"
for page in overview drivers flags exposure dealers dealer guide; do
  for theme in light dark; do
    flag=(); [[ $theme == dark ]] && flag=(--force-dark-mode --blink-settings=preferredColorScheme=0) || flag=(--blink-settings=preferredColorScheme=1)
    "$CHROME" --headless=new --disable-gpu --hide-scrollbars --window-size=1360,2000 $flag \
      --screenshot="screenshots/${page}-${theme}.png" "$FILE#$page" >/dev/null 2>&1
  done
done
# every page must render and log no script errors
fail=0
for page in overview drivers flags exposure dealers dealer guide; do
  log=$("$CHROME" --headless=new --disable-gpu --enable-logging=stderr --v=0 --dump-dom "$FILE#$page" 2>&1 >/tmp/drw_dom.html)
  if ! grep -q 'class="page"' /tmp/drw_dom.html || echo "$log" | grep -qi "Uncaught"; then echo "   FAIL $page"; echo "$log" | grep -i uncaught | head -3; fail=1; else echo "   ok   $page"; fi
done
[[ $fail == 0 ]] || { echo "render check failed"; exit 1; }
# the guided tour must reach every step, keep its caption on screen and close cleanly
python3 - <<'PY'
h=open("Dealer_Receivables_Watch.html",encoding="utf-8").read()
probe="""<script>addEventListener("load",()=>setTimeout(()=>{let bad=[];drwTour.start();for(let k=0;k<drwTour.steps;k++){const r=document.getElementById("tour").getBoundingClientRect();if(drwTour.step()!==k||r.top<0||r.bottom>innerHeight)bad.push(k+1);drwTour.next();}document.title=(bad.length||drwTour.step()!==-1)?"TOURFAIL "+bad.join(","):"TOUROK";},400));</script>"""
open("/tmp/drw_tour.html","w",encoding="utf-8").write(h.replace("</body>",probe+"</body>"))
PY
tour=$("$CHROME" --headless=new --disable-gpu --window-size=1360,900 --virtual-time-budget=4000 --dump-dom "file:///tmp/drw_tour.html" 2>/dev/null | grep -o 'TOUR[A-Z]*[ 0-9,]*' | head -1)
[[ $tour == TOUROK ]] && echo "   ok   tour (10 steps)" || { echo "   FAIL tour: $tour"; exit 1; }
ls screenshots
echo "5/5 note + package"
"$CHROME" --headless=new --disable-gpu --no-pdf-header-footer --print-to-pdf="$PWD/note/Note_UC09_Dealer_Receivables.pdf" "file://$PWD/note/note.html" >/dev/null 2>&1
pages=$(python3 -c "import re;print(len(re.findall(rb'/Type\\s*/Page[^s]',open('note/Note_UC09_Dealer_Receivables.pdf','rb').read())))")
[[ $pages == 1 ]] && echo "   note: 1 page" || { echo "   note runs to $pages pages: shorten note/note.html"; exit 1; }
rm -rf dist && mkdir -p dist/UC09_Dealer_Receivables/{data,screenshots,source}
P=dist/UC09_Dealer_Receivables
cp Dealer_Receivables_Watch.html note/Note_UC09_Dealer_Receivables.pdf $P/ && cp note/handin_README.md $P/README.md
cp data/*.csv data/README.md $P/data/ && cp screenshots/*.png $P/screenshots/ && cp generate_data.py $P/source/
(cd dist && zip -qr UC09_Dealer_Receivables.zip UC09_Dealer_Receivables) && echo "   dist/UC09_Dealer_Receivables.zip ($(du -h dist/UC09_Dealer_Receivables.zip | cut -f1))"
echo "done → open Dealer_Receivables_Watch.html"
