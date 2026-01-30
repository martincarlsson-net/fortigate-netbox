"""Cache manager for storing and retrieving API data locally."""
import pickle
import logging
from pathlib import Path
from typing import Any, Optional
from datetime import datetime


class CacheManager:
    """Manages local caching of API responses using pickle files."""
    
    def __init__(self, cache_dir: Path, use_cache: bool = False):
        """
        Initialize cache manager.
        
        Args:
            cache_dir: Directory to store cache files
            use_cache: If True, try to use cached data; if False, always fetch fresh data
                      Note: Data is ALWAYS cached when fetched, regardless of this flag
        """
        self.cache_dir = Path(cache_dir)
        self.use_cache = use_cache
        self.logger = logging.getLogger(__name__)
        
        # Create cache directory if it doesn't exist
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        if use_cache:
            self.logger.info(f"🔵 Cache mode: READ from cache when available")
        else:
            self.logger.info(f"🟢 Cache mode: ALWAYS fetch fresh data (but will cache it)")
        self.logger.info(f"📁 Cache directory: {cache_dir}")
    
    def _get_cache_file(self, cache_key: str) -> Path:
        """Get the path to a cache file."""
        return self.cache_dir / f"{cache_key}.pickle"
    
    def get(self, cache_key: str) -> Optional[Any]:
        """
        Retrieve data from cache.
        
        Args:
            cache_key: Unique identifier for the cached data
            
        Returns:
            Cached data if available and use_cache is True, None otherwise
        """
        if not self.use_cache:
            self.logger.debug(f"Cache disabled, skipping read for: {cache_key}")
            return None
        
        cache_file = self._get_cache_file(cache_key)
        
        if not cache_file.exists():
            self.logger.info(f"📭 Cache miss: {cache_key} (file not found)")
            return None
        
        try:
            with open(cache_file, 'rb') as f:
                data = pickle.load(f)
            
            # Get file modification time
            mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
            self.logger.info(f"✅ Cache hit: {cache_key} (cached on {mtime.strftime('%Y-%m-%d %H:%M:%S')})")
            return data
        except Exception as e:
            self.logger.error(f"❌ Error reading cache file {cache_key}: {e}")
            return None
    
    def set(self, cache_key: str, data: Any) -> None:
        """
        Store data in cache. This ALWAYS happens regardless of use_cache flag.
        
        Args:
            cache_key: Unique identifier for the cached data
            data: Data to cache
        """
        cache_file = self._get_cache_file(cache_key)
        
        try:
            with open(cache_file, 'wb') as f:
                pickle.dump(data, f)
            
            size_kb = round(cache_file.stat().st_size / 1024, 2)
            self.logger.info(f"💾 Cached: {cache_key} ({size_kb} KB)")
        except Exception as e:
            self.logger.error(f"❌ Error writing cache file {cache_key}: {e}")
    
    def delete(self, cache_key: str) -> bool:
        """
        Delete a single cache entry (best-effort).

        Returns:
            True if a cache file existed and was deleted, False otherwise.
        """
        cache_file = self._get_cache_file(cache_key)
        if not cache_file.exists():
            self.logger.debug(f"Cache delete skipped (file not found): {cache_key}")
            return False

        try:
            cache_file.unlink()
            self.logger.info(f"🗑️ Cache invalidated: {cache_key}")
            return True
        except Exception as e:
            self.logger.error(f"❌ Error deleting cache file {cache_key}: {e}")
            return False

    def list_cache_files(self) -> list[dict]:
        """List all cache files with metadata."""
        cache_files = []
        for cache_file in self.cache_dir.glob("*.pickle"):
            stat = cache_file.stat()
            cache_files.append({
                'key': cache_file.stem,
                'file': cache_file.name,
                'size_bytes': stat.st_size,
                'size_kb': round(stat.st_size / 1024, 2),
                'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            })
        return sorted(cache_files, key=lambda x: x['modified'], reverse=True)
