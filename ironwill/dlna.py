"""Share videos on the home network as a DLNA media server (Playback > Share to TV).

Roku Media Player (and smart TVs, game consoles, VLC) list DLNA servers and play from them. This is the smallest
server they accept: SSDP announce/answer on 239.255.255.250:1900, a device description, ContentDirectory Browse
(one folder: the files shared by the player), and plain HTTP file serving with Range requests for seeking.
"""
import html
import mimetypes
import re
import socket
import struct
import threading
import time
import urllib.parse
import uuid
from pathlib import Path

from .cast import DLNA_FEATURES, _Handler, _Server

SSDP_ADDR = ("239.255.255.250", 1900)
DEVICE_TYPE = "urn:schemas-upnp-org:device:MediaServer:1"
CDS = "urn:schemas-upnp-org:service:ContentDirectory:1"
CMS = "urn:schemas-upnp-org:service:ConnectionManager:1"
UUID = "uuid:" + str(uuid.uuid5(uuid.NAMESPACE_DNS, socket.gethostname() + ".ironwill.dlna"))

DESCRIPTION = """<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0"><specVersion><major>1</major><minor>0</minor></specVersion>
<device><deviceType>{dt}</deviceType><friendlyName>{name}</friendlyName><manufacturer>Iron Will</manufacturer>
<modelName>Iron Will Media Player</modelName><UDN>{udn}</UDN>
<serviceList>
<service><serviceType>{cds}</serviceType><serviceId>urn:upnp-org:serviceId:ContentDirectory</serviceId>
<SCPDURL>/cds.xml</SCPDURL><controlURL>/control/cds</controlURL><eventSubURL>/event/cds</eventSubURL></service>
<service><serviceType>{cms}</serviceType><serviceId>urn:upnp-org:serviceId:ConnectionManager</serviceId>
<SCPDURL>/cms.xml</SCPDURL><controlURL>/control/cms</controlURL><eventSubURL>/event/cms</eventSubURL></service>
</serviceList></device></root>"""

SCPD = """<?xml version="1.0"?><scpd xmlns="urn:schemas-upnp-org:service-1-0">
<specVersion><major>1</major><minor>0</minor></specVersion><actionList>{actions}</actionList>
<serviceStateTable><stateVariable sendEvents="no"><name>A_ARG_TYPE_String</name><dataType>string</dataType>
</stateVariable></serviceStateTable></scpd>"""


def _action(name, args_in, args_out):
    a = "".join(f"<argument><name>{n}</name><direction>in</direction>"
                f"<relatedStateVariable>A_ARG_TYPE_String</relatedStateVariable></argument>" for n in args_in)
    a += "".join(f"<argument><name>{n}</name><direction>out</direction>"
                 f"<relatedStateVariable>A_ARG_TYPE_String</relatedStateVariable></argument>" for n in args_out)
    return f"<action><name>{name}</name><argumentList>{a}</argumentList></action>"


CDS_SCPD = SCPD.format(actions=_action("Browse", ["ObjectID", "BrowseFlag", "Filter", "StartingIndex",
                                                   "RequestedCount", "SortCriteria"],
                                       ["Result", "NumberReturned", "TotalMatches", "UpdateID"])
                       + _action("GetSystemUpdateID", [], ["Id"]) + _action("GetSearchCapabilities", [], ["SearchCaps"])
                       + _action("GetSortCapabilities", [], ["SortCaps"]))
CMS_SCPD = SCPD.format(actions=_action("GetProtocolInfo", [], ["Source", "Sink"]))


def _soap(action, service, body):
    return (f'<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            f's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
            f'<u:{action}Response xmlns:u="{service}">{body}</u:{action}Response></s:Body></s:Envelope>').encode()


def _mime(f):
    t = mimetypes.guess_type(f.name)[0]
    return t or {".mkv": "video/x-matroska", ".ts": "video/mp2t", ".m2ts": "video/mp2t"}.get(
        f.suffix.lower(), "video/mp4")


class Server:
    """A running share. set_files() changes what the TV sees; stop() takes it off the network."""

    def __init__(self, name="Iron Will", target_ip=None):
        self.name, self.files, self.update_id = name, [], 1
        self.ip = target_ip or _lan_ip()
        server = self

        class H(_Handler):
            def log_message(self, *_a):
                pass

            def do_GET(self):
                if self.path.startswith("/media/"):
                    return self._media(head=False)
                self._xml()

            def do_HEAD(self):
                if self.path.startswith("/media/"):
                    return self._media(head=True)
                self._xml()

            def _media(self, head):
                try:
                    self.file = str(server.files[int(self.path.split("/")[2].split(".")[0])])
                except (ValueError, IndexError):
                    return self.send_error(404)
                self._send(head)

            def _xml(self):
                page = {"/description.xml": DESCRIPTION.format(dt=DEVICE_TYPE, name=html.escape(server.name),
                                                               udn=UUID, cds=CDS, cms=CMS),
                        "/cds.xml": CDS_SCPD, "/cms.xml": CMS_SCPD}.get(self.path.split("?")[0])
                if page is None:
                    return self.send_error(404)
                self._reply(page.encode(), "text/xml; charset=utf-8")

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode(errors="replace")
                soap = self.headers.get("SOAPACTION", "")
                if "Browse" in soap:
                    out = server._browse(body)
                elif "GetSystemUpdateID" in soap:
                    out = _soap("GetSystemUpdateID", CDS, f"<Id>{server.update_id}</Id>")
                elif "GetSearchCapabilities" in soap:
                    out = _soap("GetSearchCapabilities", CDS, "<SearchCaps></SearchCaps>")
                elif "GetSortCapabilities" in soap:
                    out = _soap("GetSortCapabilities", CDS, "<SortCaps></SortCaps>")
                elif "GetProtocolInfo" in soap:
                    out = _soap("GetProtocolInfo", CMS, "<Source>http-get:*:*:*</Source><Sink></Sink>")
                else:
                    return self.send_error(401)
                self._reply(out, 'text/xml; charset="utf-8"')

            def do_SUBSCRIBE(self):  # some clients subscribe to events; accept and never send any
                self.send_response(200)
                self.send_header("SID", "uuid:" + str(uuid.uuid4()))
                self.send_header("TIMEOUT", "Second-1800")
                self.end_headers()

            def _reply(self, data, ctype):
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("EXT", "")
                self.end_headers()
                self.wfile.write(data)

        self.http = _Server((self.ip, 0), H)
        self.port = self.http.server_address[1]
        self.location = f"http://{self.ip}:{self.port}/description.xml"
        self.running = True
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        threading.Thread(target=self._ssdp_answer, daemon=True).start()
        threading.Thread(target=self._ssdp_alive, daemon=True).start()

    def set_files(self, files):
        self.files = [Path(f) for f in files]
        self.update_id += 1

    # ContentDirectory: one container ("0") holding the shared files ------------------------------------------
    def _browse(self, body):
        arg = lambda n: html.unescape((re.search(f"<{n}[^>]*>([^<]*)</{n}>", body) or [None, ""])[1])
        oid, flag = arg("ObjectID") or "0", arg("BrowseFlag")
        start, count = int(arg("StartingIndex") or 0), int(arg("RequestedCount") or 0)
        base = f"http://{self.ip}:{self.port}"
        if flag == "BrowseMetadata":
            if oid == "0":
                items = [f'<container id="0" parentID="-1" restricted="1" childCount="{len(self.files)}">'
                         f'<dc:title>{html.escape(self.name)}</dc:title><upnp:class>object.container</upnp:class>'
                         f'</container>']
            else:
                items = [self._item(int(oid), base)] if oid.isdigit() and int(oid) < len(self.files) else []
            total = 1
        else:
            chosen = list(range(len(self.files)))[start:start + count if count else None]
            items, total = [self._item(i, base) for i in chosen], len(self.files)
        didl = ('<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
                'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
                + "".join(items) + "</DIDL-Lite>")
        return _soap("Browse", CDS, f"<Result>{html.escape(didl)}</Result><NumberReturned>{len(items)}"
                                    f"</NumberReturned><TotalMatches>{total}</TotalMatches>"
                                    f"<UpdateID>{self.update_id}</UpdateID>")

    def _item(self, i, base):
        f = self.files[i]
        mime = _mime(f)
        cls = "object.item.audioItem.musicTrack" if mime.startswith("audio") else "object.item.videoItem"
        try:
            size = f.stat().st_size
        except OSError:
            size = 0
        url = f"{base}/media/{i}{f.suffix.lower()}"
        return (f'<item id="{i}" parentID="0" restricted="1"><dc:title>{html.escape(f.stem)}</dc:title>'
                f'<upnp:class>{cls}</upnp:class><res protocolInfo="http-get:*:{mime}:{DLNA_FEATURES}" size="{size}">'
                f'{html.escape(url)}</res></item>')

    # SSDP ---------------------------------------------------------------------------------------------------
    def _notify(self, nts):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(self.ip))
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        for nt, usn in self._targets():
            msg = (f"NOTIFY * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nCACHE-CONTROL: max-age=1800\r\n"
                   f"LOCATION: {self.location}\r\nNT: {nt}\r\nNTS: {nts}\r\nSERVER: Windows/10 UPnP/1.0 IronWill/1\r\n"
                   f"USN: {usn}\r\n\r\n")
            s.sendto(msg.encode(), SSDP_ADDR)
        s.close()

    def _targets(self):
        return [("upnp:rootdevice", f"{UUID}::upnp:rootdevice"), (UUID, UUID),
                (DEVICE_TYPE, f"{UUID}::{DEVICE_TYPE}"), (CDS, f"{UUID}::{CDS}"), (CMS, f"{UUID}::{CMS}")]

    def _ssdp_alive(self):
        while self.running:
            try:
                self._notify("ssdp:alive")
            except OSError:
                pass
            for _ in range(60):
                if not self.running:
                    return
                time.sleep(0.5)

    def _ssdp_answer(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", 1900))
        s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                     struct.pack("4s4s", socket.inet_aton(SSDP_ADDR[0]), socket.inet_aton(self.ip)))
        s.settimeout(1)
        self._ssdp_sock = s
        while self.running:
            try:
                data, addr = s.recvfrom(4096)
            except (socket.timeout, OSError):
                continue
            text = data.decode(errors="replace")
            if not text.startswith("M-SEARCH"):
                continue
            st = (re.search(r"(?im)^st:\s*(.+?)\s*$", text) or [None, ""])[1]
            for nt, usn in self._targets():
                if st in ("ssdp:all", nt):
                    reply = (f"HTTP/1.1 200 OK\r\nCACHE-CONTROL: max-age=1800\r\nEXT:\r\nLOCATION: {self.location}\r\n"
                             f"SERVER: Windows/10 UPnP/1.0 IronWill/1\r\nST: {nt}\r\nUSN: {usn}\r\n\r\n")
                    try:
                        s.sendto(reply.encode(), addr)
                    except OSError:
                        pass

    def stop(self):
        self.running = False
        try:
            self._notify("ssdp:byebye")
        except OSError:
            pass
        self.http.shutdown()
        self.http.server_close()
        try:
            self._ssdp_sock.close()
        except Exception:
            pass


def _lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("239.255.255.250", 1900))
        return s.getsockname()[0]
    finally:
        s.close()


# Client side: browse other media servers on the network (Plex, NAS, Windows Media sharing, another Iron Will) -----
def find_servers(timeout=3.0):
    """[(name, control_url)] for every media server that offers a ContentDirectory."""
    import urllib.request
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.settimeout(0.5)
    msg = (f'M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\nMX: 2\r\n'
           f"ST: {DEVICE_TYPE}\r\n\r\n").encode()
    for _ in range(2):
        s.sendto(msg, SSDP_ADDR)
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
        svc = re.search(r"<service>(?:(?!</service>).)*?ContentDirectory(?:(?!</service>).)*?</service>", x, re.S)
        if not svc:
            continue
        ctrl = re.search(r"<controlURL>([^<]*)</controlURL>", svc.group(0)).group(1)
        name = (re.search(r"<friendlyName>([^<]*)</friendlyName>", x) or [None, "Media server"])[1]
        out.append((html.unescape(name), urllib.parse.urljoin(loc, ctrl)))
    return out


def browse(control_url, object_id="0"):
    """Children of a folder on a media server: [(kind, title, id_or_url)], kind 'folder' or 'item'."""
    import urllib.request
    body = (f'<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            f's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body><u:Browse xmlns:u="{CDS}">'
            f"<ObjectID>{html.escape(object_id)}</ObjectID><BrowseFlag>BrowseDirectChildren</BrowseFlag>"
            f"<Filter>*</Filter><StartingIndex>0</StartingIndex><RequestedCount>500</RequestedCount>"
            f"<SortCriteria></SortCriteria></u:Browse></s:Body></s:Envelope>").encode()
    req = urllib.request.Request(control_url, data=body, method="POST", headers={
        "Content-Type": 'text/xml; charset="utf-8"', "SOAPACTION": f'"{CDS}#Browse"'})
    raw = urllib.request.urlopen(req, timeout=10).read().decode(errors="replace")
    didl = html.unescape((re.search(r"<Result>(.*?)</Result>", raw, re.S) or [None, ""])[1])
    out = []
    for kind, block in re.findall(r"<(container|item)\b(.*?)</\1>", didl, re.S):
        title = html.unescape((re.search(r"<dc:title>(.*?)</dc:title>", block, re.S) or [None, "?"])[1])
        if kind == "container":
            out.append(("folder", title, (re.search(r'id="([^"]*)"', block) or [None, ""])[1]))
        else:
            res = re.search(r"<res[^>]*>(.*?)</res>", block, re.S)
            if res:
                out.append(("item", title, html.unescape(res.group(1).strip())))
    return out
