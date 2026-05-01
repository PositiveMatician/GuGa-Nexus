import sys
import time

# Simple script that asks for input to test interactive mode
try:
    print("Welcome to the interactive test.")
    sys.stdout.flush()
    name = input("Enter your name: ")
    print(f"Hello, {name}!")
    sys.stdout.flush()
except EOFError:
    pass
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
