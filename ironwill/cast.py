"""Cast to a Roku on the home network (Playback > Cast to TV).

Rokus answer an SSDP search for "roku:ecp" and take commands over plain HTTP on port 8060 (Roku's External Control
Protocol). Casting = serve the playing file from this PC over HTTP (with Range requests, so the Roku can seek), then
ask the Roku to open that address in its built-in media player (channel 2213). Pause / skip are ECP key presses.
A Roku whose "Control by mobile apps" setting is Limited or Disabled refuses the launch; we say so.
"""
import http.server
import mimetypes
import os
import re
import socket
import socketserver
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

MEDIA_PLAYER = "2213"  # Roku Media Player channel id
DLNA_FEATURES = "DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000"


def discover(timeout=3.0):
    """[(name, model, base_url, control_mode)] for every Roku that answers on the local network."""
    msg = ("M-SEARCH * HTTP/1.1\r\nHost: 239.255.255.250:1900\r\nMan: \"ssdp:discover\"\r\n"
           "ST: roku:ecp\r\nMX: 2\r\n\r\n").encode()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.settimeout(0.5)
    s.sendto(msg, ("239.255.255.250", 1900))
    found, end = set(), time.time() + timeout
    while time.time() < end:
        try:
            data, _addr = s.recvfrom(4096)
        except socket.timeout:
            continue
        text = data.decode(errors="replace")
        loc = re.search(r"(?im)^location:\s*(\S+)", text)
        if loc and re.search(r"(?im)^st:\s*roku:ecp", text) or loc and ":8060" in loc.group(1):
            found.add(loc.group(1).rstrip("/") + "/")
    s.close()
    rokus = []
    for base in sorted(found):
        try:
            info = urllib.request.urlopen(base + "query/device-info", timeout=3).read().decode(errors="replace")
        except OSError:
            continue
        tag = lambda k: (re.search(f"<{k}>([^<]*)</{k}>", info) or [None, ""])[1]
        rokus.append((tag("friendly-device-name") or tag("user-device-name") or "Roku",
                      f"{tag('model-name')} {tag('model-number')}".strip(), base, tag("ecp-setting-mode") or "default"))
    return rokus


def _lan_ip_for(base):
    """This PC's address on the same network as the Roku (the one the Roku can reach)."""
    host = urllib.parse.urlparse(base).hostname
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((host, 8060))
        return s.getsockname()[0]
    finally:
        s.close()


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Serves exactly one file, with Range support (Rokus seek with Range requests)."""
    file = None

    def log_message(self, *_args):
        pass

    def do_HEAD(self):
        self._send(head=True)

    def do_GET(self):
        self._send(head=False)

    def _send(self, head):
        f = Path(self.file)
        size = f.stat().st_size
        start, end = 0, size - 1
        rng = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if rng and (rng.group(1) or rng.group(2)):
            if rng.group(1):
                start = int(rng.group(1))
                end = int(rng.group(2)) if rng.group(2) else size - 1
            else:  # "bytes=-N": the last N bytes
                start = max(0, size - int(rng.group(2)))
            end = min(end, size - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(f.name)[0] or "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        # DLNA TVs (Samsung) ask for these and give up without them: streaming, seekable by byte range
        self.send_header("transferMode.dlna.org", "Streaming")
        self.send_header("contentFeatures.dlna.org", DLNA_FEATURES)
        self.end_headers()
        if head:
            return
        with f.open("rb") as fh:
            fh.seek(start)
            left = end - start + 1
            try:
                while left > 0:
                    chunk = fh.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
            except (ConnectionError, OSError):
                pass  # the Roku closed the connection (seeking, stopping): normal


class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class Cast:
    """One cast session: serves a file and drives one Roku."""

    def __init__(self, base, name=""):
        self.base, self.name, self.server = base, name, None

    def _post(self, path):
        req = urllib.request.Request(self.base + path, data=b"", method="POST")
        urllib.request.urlopen(req, timeout=5).read()

    def play(self, file):
        """Start the file on the Roku. Raises OSError with a readable message if the Roku refuses."""
        self.stop_serving()
        ip = _lan_ip_for(self.base)
        handler = type("H", (_Handler,), {"file": str(file)})
        self.server = _Server((ip, 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        url = f"http://{ip}:{self.server.server_address[1]}/{urllib.parse.quote(Path(file).name)}"
        q = urllib.parse.urlencode({"t": "v", "u": url, "videoName": Path(file).stem,
                                     "videoFormat": Path(file).suffix.lstrip(".").lower()})
        try:
            self._post(f"launch/{MEDIA_PLAYER}?{q}")
        except urllib.error.HTTPError as e:
            self.stop_serving()
            if e.code in (401, 403):
                raise OSError(f"{self.name or 'The Roku'} blocks apps: on the Roku set Settings > System > "
                              "Advanced system settings > Control by mobile apps > Network access to Permissive")
            raise OSError(f"The Roku said {e.code}")
        except OSError as e:
            self.stop_serving()
            raise OSError(f"Couldn't reach {self.name or 'the Roku'} ({e})")

    def key(self, name):
        """Roku remote keys: Play (toggles pause), Rev, Fwd, InstantReplay, Back, Home."""
        try:
            self._post(f"keypress/{name}")
        except OSError:
            pass

    def stop(self):
        self.key("Back")
        self.stop_serving()

    def stop_serving(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None


# Smart TVs, consoles (DLNA "media renderers": Samsung, LG, Sony, Xbox…) ---------------------------------------
AVT = "urn:schemas-upnp-org:service:AVTransport:1"


def find_renderers(timeout=3.0):
    """[(name, model, control_url)] for every device that can be told to play a URL (has AVTransport)."""
    msg = ('M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\nMX: 2\r\n'
           'ST: urn:schemas-upnp-org:device:MediaRenderer:1\r\n\r\n').encode()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.settimeout(0.5)
    for _ in range(2):  # UDP over Wi-Fi drops packets; TVs answer twice at worst
        s.sendto(msg, ("239.255.255.250", 1900))
    locs, end = set(), time.time() + timeout
    while time.time() < end:
        try:
            data, _a = s.recvfrom(4096)
        except socket.timeout:
            continue
        m = re.search(r"(?im)^location:\s*(\S+)", data.decode(errors="replace"))
        if m:
            locs.add(m.group(1))
    s.close()
    out = []
    for loc in sorted(locs):
        try:
            x = urllib.request.urlopen(loc, timeout=3).read().decode(errors="replace")
        except OSError:
            continue
        svc = re.search(r"<service>(?:(?!</service>).)*?" + re.escape(AVT) + r"(?:(?!</service>).)*?</service>", x, re.S)
        if not svc:
            continue
        ctrl = re.search(r"<controlURL>([^<]*)</controlURL>", svc.group(0)).group(1)
        tag = lambda k: (re.search(f"<{k}>([^<]*)</{k}>", x) or [None, ""])[1]
        out.append((tag("friendlyName") or "TV", f"{tag('manufacturer')} {tag('modelName')}".strip(),
                    urllib.parse.urljoin(loc, ctrl)))
    return out


class Renderer:
    """Push a file to a smart TV and drive it: the TV fetches the file from a small server on this PC."""

    def __init__(self, control_url, name=""):
        self.control, self.name, self.server, self.url = control_url, name, None, ""

    def _call(self, action, args=""):
        body = (f'<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
                f's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body><u:{action} xmlns:u="{AVT}">'
                f"<InstanceID>0</InstanceID>{args}</u:{action}></s:Body></s:Envelope>").encode()
        req = urllib.request.Request(self.control, data=body, method="POST", headers={
            "Content-Type": 'text/xml; charset="utf-8"', "SOAPACTION": f'"{AVT}#{action}"'})
        return urllib.request.urlopen(req, timeout=8).read().decode(errors="replace")

    def play(self, file):
        import html as _h
        self.stop_serving()
        host = urllib.parse.urlparse(self.control).hostname
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((host, 9))
        ip = s.getsockname()[0]
        s.close()
        handler = type("H", (_Handler,), {"file": str(file)})
        self.server = _Server((ip, 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        f = Path(file)
        self.url = f"http://{ip}:{self.server.server_address[1]}/media{f.suffix.lower()}"
        mime = mimetypes.guess_type(f.name)[0] or {".mkv": "video/x-matroska"}.get(f.suffix.lower(), "video/mp4")
        meta = ('<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" xmlns:dc="http://purl.org/dc/elements/1.1/" '
                'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/"><item id="1" parentID="0" restricted="1">'
                f'<dc:title>{_h.escape(f.stem)}</dc:title><upnp:class>object.item.videoItem</upnp:class>'
                f'<res protocolInfo="http-get:*:{mime}:{DLNA_FEATURES}">{_h.escape(self.url)}</res></item></DIDL-Lite>')
        try:
            self._call("Stop")
        except OSError:
            pass  # nothing was playing
        try:
            self._call("SetAVTransportURI", f"<CurrentURI>{_h.escape(self.url)}</CurrentURI>"
                                             f"<CurrentURIMetaData>{_h.escape(meta)}</CurrentURIMetaData>")
            self._call("Play", "<Speed>1</Speed>")
        except urllib.error.HTTPError as e:
            self.stop_serving()
            raise OSError(f"{self.name or 'The TV'} refused it ({e.code}): it may not play {f.suffix} files")
        except OSError as e:
            self.stop_serving()
            raise OSError(f"Couldn't reach {self.name or 'the TV'} ({e})")

    def pause(self):
        self._safe("Pause")

    def resume(self):
        self._safe("Play", "<Speed>1</Speed>")

    def seek(self, seconds):
        h, rem = divmod(int(max(0, seconds)), 3600)
        self._safe("Seek", f"<Unit>REL_TIME</Unit><Target>{h}:{rem // 60:02}:{rem % 60:02}</Target>")

    def position(self):
        """(position, duration) in seconds as the TV reports them, or (None, None)."""
        try:
            x = self._call("GetPositionInfo")
        except OSError:
            return None, None
        secs = lambda t: sum(int(float(p)) * m for p, m in zip(reversed(t.split(":")), (1, 60, 3600))) if t and ":" in t else None
        g = lambda k: (re.search(f"<{k}>([^<]*)</{k}>", x) or [None, ""])[1]
        return secs(g("RelTime")), secs(g("TrackDuration"))

    def stop(self):
        self._safe("Stop")
        self.stop_serving()

    def _safe(self, action, args=""):
        try:
            self._call(action, args)
        except OSError:
            pass

    def stop_serving(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
