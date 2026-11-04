# Third-party notices

RockSteady Fix is licensed under the GNU General Public License v3.0 (see `LICENSE`). Its source code is in this
project's GitHub repository, and `build.bat` with the pinned `requirements*.txt` rebuilds the `.exe`.

`RockSteadyFix.exe` bundles the components below. They keep their own licenses. The release ZIP contains the available
license texts in the `licenses` folder. Because x264 and x265 are GPL-licensed and the bundled FFmpeg links them, the
`.exe` as a whole is distributed under GPL-3.0.

The exact source code of the bundled FFmpeg, x264 and x265, with the build scripts and patches used to compile them, is
attached to the release as `RockSteadyFix_v1.6.1_third_party_source_code.zip`.

| Component | Version | License | Source |
|---|---|---|---|
| Python | 3.13.1 | PSF-2.0 | https://www.python.org/ |
| Tcl/Tk (`tcl86t`, `tk86t`) | 8.6 | Tcl/Tk license (BSD-style) | https://www.tcl-lang.org/ |
| PyAV (`av`) | 19.0.1 | BSD-3-Clause | https://github.com/PyAV-Org/PyAV |
| FFmpeg (libavcodec etc., via PyAV) | 9.0.2 | LGPL-3.0-or-later (built with `--enable-version3`, without `--enable-nonfree`) | https://ffmpeg.org/ · build scripts: https://github.com/PyAV-Org/pyav-ffmpeg |
| x264 (via PyAV) | build 165, commit b35605a | GPL-2.0-or-later | https://www.videolan.org/developers/x264.html |
| x265 (via PyAV) | 4.3 | GPL-2.0-or-later | https://www.videolan.org/developers/x265.html |
| dav1d, SVT-AV1, libvpx, libwebp, Opus, VMAF, oneVPL, zlib, libiconv, MinGW runtime (via PyAV) | as shipped in `av` 19.0.1 | BSD / MIT / Zlib / LGPL-2.1-or-later / GPL with GCC Runtime Library Exception (each per its project) | https://github.com/PyAV-Org/pyav-ffmpeg |
| OpenCV (`opencv-python-headless`), with its FFmpeg plugin | 5.0.0.93 | Apache-2.0; bundled parts per its `LICENSE-3RD-PARTY.txt`; plugin LGPL | https://github.com/opencv/opencv-python |
| NumPy, with OpenBLAS | 2.5.4 | BSD-3-Clause and others (see its license file) | https://numpy.org/ |
| CustomTkinter | 6.0.0 | MIT | https://github.com/TomSchimansky/CustomTkinter |
| darkdetect | 0.8.0 | BSD-3-Clause | https://github.com/albertosottile/darkdetect |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging |
| tkinterdnd2, with tkdnd | 0.6.4 | MIT; tkdnd BSD-style | https://github.com/Eliav2/tkinterdnd2 |
| Pillow | 13.0.0 | MIT-CMU | https://github.com/python-pillow/Pillow |
| PyInstaller bootloader | 6.22.3 | GPL-2.0-or-later with bootloader exception | https://github.com/pyinstaller/pyinstaller |
| Microsoft Visual C++ runtime | – | Microsoft redistributable | https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist |

"DJI", "O4" and "RockSteady" are trademarks of their owners; "Instagram" is a trademark of Meta. This project is not
affiliated with or endorsed by any of them.
