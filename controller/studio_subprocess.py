"""Flags for background helpers; a detached parent must not open child consoles."""
import subprocess


def background_creationflags():
    return getattr(subprocess, 'CREATE_NO_WINDOW', 0)
