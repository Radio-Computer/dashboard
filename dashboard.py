from flask import Flask, render_template, Response, jsonify, request
from functools import wraps
import subprocess
import psutil
import time
import json
import os
from datetime import datetime

app = Flask(__name__)

# Default configuration
DEFAULT_CONFIG = {
    'username': 'admin',
    'password': 'admin',
    'services': [
        'nginx',
        'ssh',
        'docker',
        'postgresql',
        'redis'
    ]
}

def load_config(config_file='config.json'):
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
                print(f"  configuration loaded from {config_file}")
                return config
        except Exception as e:
            print(f"  error loading config: {e}")
            print("  using default configuration")
            return DEFAULT_CONFIG
    else:
        # Create default config file
        try:
            with open(config_file, 'w') as f:
                json.dump(DEFAULT_CONFIG, f, indent=4)
            print(f"  created default config file: {config_file}")
            print("  edit this file to customize credentials and services")
        except Exception as e:
            print(f"  could not create config file: {e}")
        return DEFAULT_CONFIG

# Load configuration
CONFIG = load_config()
USERNAME = CONFIG['username']
PASSWORD = CONFIG['password']
SERVICES = CONFIG['services']

login_attempts = {}

def check_auth(username, password):
    ip = request.remote_addr
    if login_attempts.get(ip, 0) > 5:
        time.sleep(3)
    ok = username == USERNAME and password == PASSWORD
    login_attempts[ip] = 0 if ok else login_attempts.get(ip, 0) + 1
    return ok
        
def authenticate():
    return Response(
        'Authentication required', 401,
        {'WWW-Authenticate': 'Basic realm="System Monitor"'}
    )

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

def get_service_status(service_name):
    try:
        result = subprocess.run(
            ['systemctl', 'status', service_name],
            capture_output=True,
            text=True,
            timeout=2
        )
        
        # Parse status
        output = result.stdout
        active = 'unknown'
        sub = 'unknown'
        
        for line in output.split('\n'):
            line = line.strip()
            if 'Active:' in line:
                parts = line.split()
                if len(parts) >= 2:
                    active = parts[1]
                    if len(parts) >= 3:
                        sub = parts[2].strip('()')
        
        return {
            'name': service_name,
            'active': active,
            'sub': sub
        }
    except Exception as e:
        return {
            'name': service_name,
            'active': 'error',
            'sub': str(e)[:20]
        }

def get_service_logs(service_name, lines=100):
    try:
        result = subprocess.run(
            ['journalctl', '-u', service_name, '-n', str(lines), '--no-pager'],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.stdout
    except Exception as e:
        return f"Error fetching logs: {str(e)}"

def format_bytes(bytes):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes < 1024.0:
            return f"{bytes:.1f}{unit}"
        bytes /= 1024.0
    return f"{bytes:.1f}PB"

def format_uptime(seconds):
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    return f"{int(days)}d {int(hours)}h {int(minutes)}m"

def get_system_data():
    # CPU
    cpu_percent = psutil.cpu_percent(interval=1)
    cpu_count = psutil.cpu_count()
    load_avg = ', '.join([f"{x:.2f}" for x in psutil.getloadavg()])
    
    # Memory
    mem = psutil.virtual_memory()
    mem_total = format_bytes(mem.total)
    mem_used = format_bytes(mem.used)
    mem_available = format_bytes(mem.available)
    mem_percent = mem.percent
    
    # Disk
    disk = psutil.disk_usage('/')
    disk_total = format_bytes(disk.total)
    disk_used = format_bytes(disk.used)
    disk_free = format_bytes(disk.free)
    disk_percent = disk.percent
    
    # Network
    net = psutil.net_io_counters()
    net_sent = format_bytes(net.bytes_sent)
    net_recv = format_bytes(net.bytes_recv)
    
    # Uptime
    uptime = format_uptime(time.time() - psutil.boot_time())
    
    # Services
    services = [get_service_status(svc) for svc in SERVICES]
    
    # Top processes
    top_processes = []
    for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'username']):
        try:
            info = proc.info
            top_processes.append({
                'pid': info['pid'],
                'name': info['name'][:30],
                'cpu': f"{info['cpu_percent']:.1f}%",
                'mem': f"{info['memory_percent']:.1f}%",
                'user': info['username'][:15]
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    
    top_processes = sorted(top_processes, key=lambda x: float(x['cpu'].strip('%')), reverse=True)[:10]
    
    return {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'cpu_percent': cpu_percent,
        'cpu_count': cpu_count,
        'load_avg': load_avg,
        'mem_total': mem_total,
        'mem_used': mem_used,
        'mem_available': mem_available,
        'mem_percent': mem_percent,
        'disk_total': disk_total,
        'disk_used': disk_used,
        'disk_free': disk_free,
        'disk_percent': disk_percent,
        'net_sent': net_sent,
        'net_recv': net_recv,
        'uptime': uptime,
        'services': services,
        'top_processes': top_processes
    }

@app.route('/')
@requires_auth
def index():
    return render_template('dashboard.html')

@app.route('/api/data')
@requires_auth
def api_data():
    return jsonify(get_system_data())

@app.route('/api/logs/<service_name>')
@requires_auth
def api_logs(service_name):
    lines = request.args.get('lines', 100, type=int)
    logs = get_service_logs(service_name, lines)
    if service_name in SERVICES:
        return jsonify({'service': service_name, 'logs': logs})
    else:
        return jsonify({'service': 'not allowed', 'logs': 'not allowed'})

if __name__ == '__main__':
    print("Starting System Monitor Dashboard...")
    print("Access at: http://localhost:5000")
    print(f"\nDefault credentials:")
    print(f"  Username: {USERNAME}")
    print(f"  Password: {PASSWORD}")
    print(f"\nMonitoring services:", ', '.join(SERVICES))
    print("\nPress Ctrl+C to stop")
    app.run(host='127.0.0.1', port=5000, debug=False)
