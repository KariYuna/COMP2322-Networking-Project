#!/usr/bin/env python3
"""
Multi-threaded HTTP Web Server
Course  : Comp 2322 Computer Networking
Language: Python 3  (standard library only - no HTTPServer used)

Features (all rubric items covered)
-------------------------------------
Methods      : GET (text + images), HEAD
Status codes : 200 OK | 304 Not Modified | 400 Bad Request |
               403 Forbidden | 404 Not Found
Headers      : Last-Modified, If-Modified-Since, Connection (keep-alive/close)
Logging      : client hostname/IP, timestamp, requested file, response code
Concurrency  : one daemon thread per accepted TCP connection
"""

import socket
import threading
import os
import stat
import datetime
import mimetypes
import time
from email.utils import parsedate_to_datetime, formatdate

# ============================================================
# Configuration
# ============================================================

HOST               = '127.0.0.1'
PORT               = 8080
SERVER_ROOT        = './www'
LOG_FILE           = 'server.log'
BUFFER_SIZE        = 4096
KEEP_ALIVE_TIMEOUT = 30
MAX_QUEUED_CONNS   = 10

# ============================================================
# Thread-safe logger
# ============================================================

_log_lock = threading.Lock()


def write_log(client_ip, client_hostname, requested_file, response_code):
    """Append one record to the log file (thread-safe) and print to stdout.

    Format:  YYYY-MM-DD HH:MM:SS | hostname (ip) | /path | status_code
    """
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    record = (
        f"{timestamp} | {client_hostname} ({client_ip}) | "
        f"{requested_file} | {response_code}"
    )
    with _log_lock:
        with open(LOG_FILE, 'a', encoding='utf-8') as fh:
            fh.write(record + '\n')
    print(f'  [LOG] {record}')


def resolve_hostname(ip_address):
    """Attempt reverse DNS lookup; return the IP string on failure."""
    try:
        return socket.getfqdn(ip_address)
    except Exception:
        return ip_address

# ============================================================
# MIME-type helper
# ============================================================

def get_content_type(file_path):
    """Return the MIME type inferred from file_path extension."""
    mime_type, _ = mimetypes.guess_type(file_path)
    return mime_type if mime_type else 'application/octet-stream'

# ============================================================
# Permission helper  (correct even when the process runs as root)
# ============================================================

def has_read_permission(file_path):
    """Return True if the file has at least one read bit set.

    Uses os.stat() mode bits instead of os.access() so the result is
    correct even when the server process runs as root (os.access always
    returns True for root regardless of the file mode).
    """
    try:
        mode = os.stat(file_path).st_mode
        return bool(mode & (stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH))
    except OSError:
        return False

# ============================================================
# HTTP response builders
# ============================================================

def build_response_headers(status_code, status_text, headers):
    """Return HTTP status line + header fields as bytes.

    Two trailing empty strings joined with CRLF produce the mandatory
    CRLFCRLF blank line that ends the header section.
    """
    lines = [f'HTTP/1.1 {status_code} {status_text}']
    for name, value in headers.items():
        lines.append(f'{name}: {value}')
    lines.append('')
    lines.append('')
    return '\r\n'.join(lines).encode('utf-8')


def send_error_response(conn, client_ip, client_hostname,
                        requested_path, status_code, status_text, keep_alive):
    """Build a minimal HTML error page, send it, and write to log."""
    html_body = (
        f'<!DOCTYPE html>\n<html>\n'
        f'<head><title>{status_code} {status_text}</title></head>\n'
        f'<body>\n  <h1>{status_code} {status_text}</h1>\n'
        f'  <p>Cannot fulfil request for <code>{requested_path}</code>.</p>\n'
        f'</body>\n</html>\n'
    ).encode('utf-8')

    resp_headers = {
        'Content-Type':   'text/html; charset=utf-8',
        'Content-Length': str(len(html_body)),
        'Date':           formatdate(usegmt=True),
        'Server':         'PythonHTTPServer/1.0',
        'Connection':     'keep-alive' if keep_alive else 'close',
    }
    try:
        conn.sendall(
            build_response_headers(status_code, status_text, resp_headers)
            + html_body
        )
    except socket.error:
        pass
    write_log(client_ip, client_hostname, requested_path, status_code)

# ============================================================
# HTTP request parser
# ============================================================

def parse_http_request(raw_request):
    """Parse a raw HTTP request string.

    Returns (method, path, http_version, headers_dict).
    Raises ValueError if the request line is missing or malformed.
    """
    lines = raw_request.split('\r\n')
    if not lines or not lines[0].strip():
        raise ValueError('Empty or missing request line.')

    parts = lines[0].split()
    if len(parts) != 3:
        raise ValueError(
            f'Malformed request line (expected 3 tokens, '
            f'got {len(parts)}): {lines[0]!r}'
        )

    method       = parts[0].upper()
    path         = parts[1]
    http_version = parts[2]

    headers = {}
    for line in lines[1:]:
        if not line:
            break
        if ':' in line:
            name, _, value = line.partition(':')
            headers[name.strip().lower()] = value.strip()

    return method, path, http_version, headers

# ============================================================
# Core request handler  (implements all rubric requirements)
# ============================================================

def handle_http_request(conn, client_ip, client_hostname, raw_request):
    """Process one HTTP request and send the appropriate response.

    Stage 1: display the raw request on stdout  (spec requirement).
    Stage 2: parse and generate the correct HTTP response.

    Returns True  -> keep the connection alive (persistent connection)
             False -> close the connection after this response
    """
    time.sleep(10)  # It gives you 10 seconds to run the second command.

    # ── Stage 1: display raw request ─────────────────────────────────────────
    separator = '-' * 60
    print(f'\n{separator}')
    print(f'  Request from {client_ip} ({client_hostname})')
    print(raw_request[:800])
    print(separator)

    requested_path = '/'   # used for logging even if parsing fails

    # ── Stage 2: parse ────────────────────────────────────────────────────────
    try:
        method, path, http_version, req_headers = parse_http_request(raw_request)
    except ValueError as exc:
        print(f'  [WARN] Bad request: {exc}')
        send_error_response(conn, client_ip, client_hostname, requested_path,
                            400, 'Bad Request', keep_alive=False)
        return False

    requested_path = path

    # ── Determine connection persistence ──────────────────────────────────────
    # HTTP/1.1 is persistent by default; HTTP/1.0 is non-persistent by default.
    connection_directive = req_headers.get('connection', '').lower()
    if http_version == 'HTTP/1.1':
        keep_alive = (connection_directive != 'close')
    else:
        keep_alive = (connection_directive == 'keep-alive')

    # ── Validate HTTP method (only GET and HEAD are supported) ─────────────────
    if method not in ('GET', 'HEAD'):
        send_error_response(conn, client_ip, client_hostname, requested_path,
                            400, 'Bad Request', keep_alive)
        return keep_alive

    # ── Resolve filesystem path  (block directory traversal) ──────────────────
    url_path = path.split('?')[0].split('#')[0]
    if url_path == '/':
        url_path = '/index.html'

    abs_server_root    = os.path.realpath(SERVER_ROOT)
    abs_requested_path = os.path.realpath(
        os.path.join(SERVER_ROOT, url_path.lstrip('/')))

    # Block any path that escapes SERVER_ROOT (e.g. /../../../etc/passwd)
    inside_root = (
        abs_requested_path.startswith(abs_server_root + os.sep)
        or abs_requested_path == abs_server_root
    )
    if not inside_root:
        send_error_response(conn, client_ip, client_hostname, requested_path,
                            403, 'Forbidden', keep_alive)
        return keep_alive

    # ── 404: file does not exist or is a directory ─────────────────────────────
    if not os.path.exists(abs_requested_path) or os.path.isdir(abs_requested_path):
        send_error_response(conn, client_ip, client_hostname, requested_path,
                            404, 'Not Found', keep_alive)
        return keep_alive

    # ── 403: file has no read permission bits set ──────────────────────────────
    if not has_read_permission(abs_requested_path):
        send_error_response(conn, client_ip, client_hostname, requested_path,
                            403, 'Forbidden', keep_alive)
        return keep_alive

    # ── Gather file metadata ───────────────────────────────────────────────────
    file_size     = os.path.getsize(abs_requested_path)
    file_mtime    = os.path.getmtime(abs_requested_path)
    last_modified = formatdate(file_mtime, usegmt=True)
    content_type  = get_content_type(abs_requested_path)

    # ── 304 Not Modified: honour If-Modified-Since ────────────────────────────
    ims_value = req_headers.get('if-modified-since', '').strip()
    if ims_value:
        try:
            ims_dt  = parsedate_to_datetime(ims_value)
            file_dt = datetime.datetime.fromtimestamp(
                file_mtime, tz=datetime.timezone.utc)
            if file_dt <= ims_dt:
                # File has not changed since the client's cached copy -> 304
                not_modified_headers = {
                    'Date':          formatdate(usegmt=True),
                    'Last-Modified': last_modified,
                    'Server':        'PythonHTTPServer/1.0',
                    'Connection':    'keep-alive' if keep_alive else 'close',
                }
                conn.sendall(
                    build_response_headers(304, 'Not Modified', not_modified_headers))
                write_log(client_ip, client_hostname, requested_path, 304)
                return keep_alive
        except Exception as exc:
            # Malformed If-Modified-Since -> ignore and serve the file normally
            print(f'  [WARN] Could not parse If-Modified-Since: {exc}')

    # ── 200 OK ────────────────────────────────────────────────────────────────
    ok_headers = {
        'Content-Type':   content_type,
        'Content-Length': str(file_size),
        'Last-Modified':  last_modified,
        'Date':           formatdate(usegmt=True),
        'Server':         'PythonHTTPServer/1.0',
        'Connection':     'keep-alive' if keep_alive else 'close',
    }
    if keep_alive:
        ok_headers['Keep-Alive'] = f'timeout={KEEP_ALIVE_TIMEOUT}, max=100'

    conn.sendall(build_response_headers(200, 'OK', ok_headers))

    # HEAD -> headers only;   GET -> headers + body
    if method == 'GET':
        with open(abs_requested_path, 'rb') as fh:
            while True:
                chunk = fh.read(BUFFER_SIZE)
                if not chunk:
                    break
                conn.sendall(chunk)

    write_log(client_ip, client_hostname, requested_path, 200)
    return keep_alive

# ============================================================
# Connection thread  (one per accepted TCP connection)
# ============================================================

def handle_connection(conn, client_address):
    """Thread entry point.  Supports HTTP persistent connections (keep-alive).

    Loops until:
      - the client closes the connection,
      - the keep-alive timeout expires with no new request, or
      - the handler signals Connection: close.
    """
    client_ip       = client_address[0]
    client_hostname = resolve_hostname(client_ip)
    print(f'\n[CONN +] {client_ip} ({client_hostname})  '
          f'active threads: {threading.active_count()-1}')

    conn.settimeout(KEEP_ALIVE_TIMEOUT)
    try:
        while True:
            # Accumulate bytes until the header section is complete
            raw_bytes = b''
            try:
                while b'\r\n\r\n' not in raw_bytes:
                    chunk = conn.recv(BUFFER_SIZE)
                    if not chunk:
                        return   # client closed connection gracefully
                    raw_bytes += chunk
            except socket.timeout:
                return   # no new request within the timeout
            except OSError as exc:
                print(f'  [ERROR] Receive error {client_ip}: {exc}')
                return

            # Trim to exactly the header section (up to and including CRLFCRLF)
            header_end   = raw_bytes.find(b'\r\n\r\n') + 4
            request_text = raw_bytes[:header_end].decode('utf-8', errors='replace')

            keep_alive = handle_http_request(
                conn, client_ip, client_hostname, request_text)
            if not keep_alive:
                return

    except OSError as exc:
        print(f'  [ERROR] Socket error {client_ip}: {exc}')
    finally:
        conn.close()
        print(f'[CONN -] {client_ip}  active threads: {threading.active_count()-2}')

# ============================================================
# Server entry point
# ============================================================

def create_sample_files():
    """Create the www/ directory and sample test files if they do not exist.

    Files created:
      index.html  - default HTML page (demonstrates GET text/html)
      hello.txt   - plain text file   (demonstrates GET text/plain)
      image.png   - small PNG image   (demonstrates GET image/png)
    """
    os.makedirs(SERVER_ROOT, exist_ok=True)

    # ---------------------------------------------------------------- HTML
    index_path = os.path.join(SERVER_ROOT, 'index.html')
    if not os.path.exists(index_path):
        with open(index_path, 'w', encoding='utf-8') as fh:
            fh.write(
                '<!DOCTYPE html>\n'
                '<html lang="en">\n'
                '<head>\n'
                '  <meta charset="UTF-8">\n'
                '  <title>COMP2322 Web Server</title>\n'
                '  <style>\n'
                '    body { font-family: Arial, sans-serif; max-width: 650px;'
                ' margin: 40px auto; padding: 0 20px; }\n'
                '    h1 { color: #8D0034; }\n'
                '    ul { line-height: 2; }\n'
                '  </style>\n'
                '</head>\n'
                '<body>\n'
                '  <h1>COMP2322 Multi-threaded Web Server</h1>\n'
                '  <p>Python HTTP/1.1 server built with raw sockets.</p>\n'
                '  <h2>Test Links</h2>\n'
                '  <ul>\n'
                '    <li><a href="/hello.txt">hello.txt</a>'
                ' &mdash; plain text file (GET text)</li>\n'
                '    <li><a href="/image.png">image.png</a>'
                ' &mdash; PNG image (GET binary)</li>\n'
                '    <li><a href="/missing.html">missing.html</a>'
                ' &mdash; triggers 404 Not Found</li>\n'
                '  </ul>\n'
                '</body>\n'
                '</html>\n'
            )
        print(f'[INIT] Created {index_path}')

    # ---------------------------------------------------------------- TXT
    txt_path = os.path.join(SERVER_ROOT, 'hello.txt')
    if not os.path.exists(txt_path):
        with open(txt_path, 'w', encoding='utf-8') as fh:
            fh.write(
                'Hello from the COMP2322 Python HTTP Server!\n'
                'This file demonstrates plain-text delivery via GET.\n'
            )
        print(f'[INIT] Created {txt_path}')

    # ---------------------------------------------------------------- PNG
    # Minimal valid 1x1 RGB PNG (68 bytes) - no external library needed.
    png_path = os.path.join(SERVER_ROOT, 'image.png')
    if not os.path.exists(png_path):
        png_bytes = bytes([
            0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
            0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,
            0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
            0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53,
            0xDE, 0x00, 0x00, 0x00, 0x0C, 0x49, 0x44, 0x41,
            0x54, 0x08, 0xD7, 0x63, 0xF8, 0xCF, 0xC0, 0x00,
            0x00, 0x00, 0x02, 0x00, 0x01, 0xE2, 0x21, 0xBC,
            0x33, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4E,
            0x44, 0xAE, 0x42, 0x60, 0x82,
        ])
        with open(png_path, 'wb') as fh:
            fh.write(png_bytes)
        print(f'[INIT] Created {png_path}')


def start_server():
    """Bind a TCP socket and spawn one daemon thread per accepted connection."""
    create_sample_files()

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # SO_REUSEADDR allows immediate restart without 'Address already in use'
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server_socket.bind((HOST, PORT))
        server_socket.listen(MAX_QUEUED_CONNS)

        print('=' * 60)
        print('  Multi-threaded HTTP Web Server')
        print(f'  Listening : http://{HOST}:{PORT}')
        print(f'  Web root  : {os.path.realpath(SERVER_ROOT)}')
        print(f'  Log file  : {os.path.realpath(LOG_FILE)}')
        print('=' * 60)
        print('  Press Ctrl+C to stop.\n')

        while True:
            conn, client_address = server_socket.accept()
            client_thread = threading.Thread(
                target=handle_connection,
                args=(conn, client_address),
                daemon=True,
                name=f'client-{client_address[0]}-{client_address[1]}'
            )
            client_thread.start()

    except KeyboardInterrupt:
        print('\n[INFO] Shutdown requested.')
    finally:
        server_socket.close()
        print('[INFO] Server socket closed.')


if __name__ == '__main__':
    start_server()