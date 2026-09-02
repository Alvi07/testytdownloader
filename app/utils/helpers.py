import re
import urllib.parse

def format_bytes(bytes_val: int | float | None) -> str:
    """Format bytes to human readable format (KB, MB, GB)."""
    if not bytes_val or bytes_val <= 0:
        return "Unknown Size"
    
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    size = float(bytes_val)
    
    while size >= 1024.0 and unit_index < len(units) - 1:
        size /= 1024.0
        unit_index += 1
        
    return f"{size:.1f} {units[unit_index]}"

def format_duration(seconds: int | float | None) -> str:
    """Format seconds into HH:MM:SS or MM:SS."""
    if not seconds or seconds <= 0:
        return "00:00"
    
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

def format_count(count: int | float | None) -> str:
    """Format view count / likes into compact format (e.g. 1.5M, 250K)."""
    if count is None or count < 0:
        return "0"
    
    count = float(count)
    if count >= 1_000_000_000:
        return f"{count / 1_000_000_000:.1f}B"
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}K"
    return str(int(count))

def sanitize_filename(filename: str, max_length: int = 150) -> str:
    """Sanitize filename to prevent OS and header injection issues."""
    if not filename:
        return "downloaded_media"
    
    # Remove characters not allowed in file names
    sanitized = re.sub(r'[\\/*?:"<>|]', "", filename)
    # Remove control characters and leading/trailing whitespace
    sanitized = re.sub(r'[\x00-\x1f\x7f]', '', sanitized).strip()
    
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length]
        
    return sanitized or "downloaded_media"

def is_valid_url(url: str) -> bool:
    """Basic validation for URL format."""
    if not url or not isinstance(url, str):
        return False
    try:
        result = urllib.parse.urlparse(url.strip())
        return all([result.scheme in ("http", "https"), result.netloc])
    except Exception:
        return False
