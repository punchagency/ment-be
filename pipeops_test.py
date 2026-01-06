import os
import sys

print("=== PIPEOPS TEST START ===")
print("Python version:", sys.version)
print("Current directory:", os.getcwd())
print("Files:", os.listdir('.'))

# Test imports
try:
    import django
    print("✅ Django import OK")
except ImportError as e:
    print("❌ Django import failed:", e)
    sys.exit(1)

try:
    import pymysql
    print("✅ pymysql import OK")
    pymysql.install_as_MySQLdb()
except ImportError as e:
    print("❌ pymysql import failed:", e)
    sys.exit(1)

print("=== PIPEOPS TEST END ===")
print("If you see this, Python can run in PipeOps")