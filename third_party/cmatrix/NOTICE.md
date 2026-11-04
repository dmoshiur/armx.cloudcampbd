# CMatrix — GPL-3.0 notice and source offer

The single-container deployment installs the **original** `cmatrix` C program
from the Debian `cmatrix` package (version 2.0, ncurses build). A.R.M.X AI runs
it as an isolated PTY subprocess and streams its terminal frames to the browser;
no CMatrix source code is copied into this repository and no CSS imitation is
used for the primary renderer.

* Upstream project: <https://github.com/abishekvashok/cmatrix>
* License: **GNU General Public License, version 3 or later** (`COPYING`)
* Canonical license text: <https://www.gnu.org/licenses/gpl-3.0.txt>
* Debian source package: <https://packages.debian.org/source/bookworm/cmatrix>
* Upstream commit (reference): `5c082c64a1296859a11bee60c8c086655953a416`
* Runtime dependencies: ncurses / terminfo (`ncurses-term`, `libncurses`)

## Written offer for corresponding source

Under GPL-3.0 §6, A.R.M.X AI's maintainer offers the complete corresponding
source code for the unmodified `cmatrix` executable distributed in the Docker
image. It is available at no charge from the upstream repository and Debian
source archive links above, and the exact Debian source package can be
retrieved with:

```sh
apt-get source cmatrix
```

This offer is valid for at least three years from 2026-11-03 and applies to
every recipient of the container image. The A.R.M.X application code is a
separate work that communicates with the executable over a PTY and does not
link to or incorporate CMatrix source code.

## Fallback renderer

`web/lib/vendor/cmatrix.mjs` is a verbatim copy of the MIT-licensed
`cmatrix@0.5.3` JavaScript port by Jakub T. Jankiewicz
(<https://github.com/jcubic/cmatrix>), including its MIT license in
`web/lib/vendor/LICENSE`. It is used **only** when the original executable
cannot start, and the UI reports that fallback explicitly. It is not a claim
that the GPL binary ran.
