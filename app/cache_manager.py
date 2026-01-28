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
            use_cache: If True, use cached data instead of making API calls
        """
        self.cache_dir = Path(cache_dir)
        self.use_cache = use_cache
        self.logger = logging.getLogger(__name__)
        
        # Create cache directory if it doesn't exist
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger.info(f"CacheManager initialized: use_cache={use_cache}, cache_dir={cache_dir}")
    
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
            return None
        
        cache_file = self._get_cache_file(cache_key)
        
        if not cache_file.exists():
            self.logger.info(f"Cache miss: {cache_key} (file not found)")
            return None
        
        try:
            with open(cache_file, 'rb') as f:
                data = pickle.load(f)
            
            # Get file modification time
            mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
            self.logger.info(f"Cache hit: {cache_key} (cached on {mtime.strftime('%Y-%m-%d %H:%M:%S')})")
            return data
        except Exception as e:
            self.logger.error(f"Error reading cache file {cache_key}: {e}")
            return None
    
    def set(self, cache_key: str, data: Any) -> None:
        """
        Store data in cache.
        
        Args:
            cache_key: Unique identifier for the cached data
            data: Data to cache
        """
        cache_file = self._get_cache_file(cache_key)
        
        try:
            with open(cache_file, 'wb') as f:
                pickle.dump(data, f)
            self.logger.info(f"Cached data saved: {cache_key} ({cache_file.stat().st_size} bytes)")
        except Exception as e:
            self.logger.error(f"Error writing cache file {cache_key}: {e}")
    
    def delete(self, cache_key: str) -> None:
        """Delete a cache file."""
        cache_file = self._get_cache_file(cache_key)
        if cache_file.exists():
            cache_file.unlink()
            self.logger.info(f"Cache deleted: {cache_key}")
    
    def clear_all(self) -> None:
        """Delete all cache files."""
        for cache_file in self.cache_dir.glob("*.pickle"):
            cache_file.unlink()
        self.logger.info("All cache files deleted")
    
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
