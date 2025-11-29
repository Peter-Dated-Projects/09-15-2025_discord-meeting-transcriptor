"""
Test script for the /deepinfo command

This script helps validate the implementation by checking:
1. All required service methods exist
2. SQL models are correctly referenced
3. Logic flow is sound
"""

import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_service_methods():
    """Check that all service methods used in /deepinfo exist."""
    from source.services.recording_sql_manager.manager import SQLRecordingManagerService
    from source.services.transcription_file_manager.manager import TranscriptionFileManagerService

    print("✓ Checking SQLRecordingManagerService methods...")
    required_methods = [
        "get_meeting",
        "get_temp_recordings_for_meeting",
        "get_persistent_recordings_for_meeting",
        "get_compiled_transcript_for_meeting",
    ]

    for method_name in required_methods:
        assert hasattr(SQLRecordingManagerService, method_name), f"Missing method: {method_name}"
        print(f"  ✓ {method_name}")

    print("\n✓ Checking TranscriptionFileManagerService methods...")
    required_methods = [
        "get_transcriptions_by_meeting",
    ]

    for method_name in required_methods:
        assert hasattr(
            TranscriptionFileManagerService, method_name
        ), f"Missing method: {method_name}"
        print(f"  ✓ {method_name}")


def test_sql_models():
    """Check that SQL models are correctly defined."""
    from source.server.sql_models import (
        CompiledTranscriptsModel,
        MeetingModel,
        RecordingModel,
        TempRecordingModel,
        UserTranscriptsModel,
    )

    print("\n✓ Checking SQL model fields...")

    # Check MeetingModel
    assert hasattr(MeetingModel, "id")
    assert hasattr(MeetingModel, "status")
    assert hasattr(MeetingModel, "started_at")
    assert hasattr(MeetingModel, "ended_at")
    assert hasattr(MeetingModel, "requested_by")
    assert hasattr(MeetingModel, "participants")
    print("  ✓ MeetingModel")

    # Check TempRecordingModel
    assert hasattr(TempRecordingModel, "id")
    assert hasattr(TempRecordingModel, "user_id")
    assert hasattr(TempRecordingModel, "meeting_id")
    assert hasattr(TempRecordingModel, "transcode_status")
    print("  ✓ TempRecordingModel")

    # Check RecordingModel
    assert hasattr(RecordingModel, "id")
    assert hasattr(RecordingModel, "user_id")
    assert hasattr(RecordingModel, "meeting_id")
    assert hasattr(RecordingModel, "duration_in_ms")
    assert hasattr(RecordingModel, "filename")
    assert hasattr(RecordingModel, "sha256")
    print("  ✓ RecordingModel")

    # Check UserTranscriptsModel
    assert hasattr(UserTranscriptsModel, "id")
    assert hasattr(UserTranscriptsModel, "user_id")
    assert hasattr(UserTranscriptsModel, "meeting_id")
    assert hasattr(UserTranscriptsModel, "transcript_filename")
    assert hasattr(UserTranscriptsModel, "sha256")
    assert hasattr(UserTranscriptsModel, "created_at")
    print("  ✓ UserTranscriptsModel")

    # Check CompiledTranscriptsModel
    assert hasattr(CompiledTranscriptsModel, "id")
    assert hasattr(CompiledTranscriptsModel, "meeting_id")
    assert hasattr(CompiledTranscriptsModel, "transcript_filename")
    assert hasattr(CompiledTranscriptsModel, "sha256")
    assert hasattr(CompiledTranscriptsModel, "created_at")
    print("  ✓ CompiledTranscriptsModel")


def test_command_structure():
    """Check that the command is properly structured."""
    import ast

    print("\n✓ Checking command structure...")

    # Read the general.py file
    with open("cogs/general.py") as f:
        content = f.read()

    # Parse the file
    tree = ast.parse(content)

    # Find the deepinfo method
    deepinfo_found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "deepinfo":
            deepinfo_found = True
            print("  ✓ deepinfo method found")

            # Check for decorators
            has_slash_command = False
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call):
                    if hasattr(decorator.func, "attr") and decorator.func.attr == "slash_command":
                        has_slash_command = True
                        print("  ✓ @commands.slash_command decorator found")

            assert has_slash_command, "Missing @commands.slash_command decorator"

            # Check parameters
            args = [arg.arg for arg in node.args.args]
            assert "self" in args, "Missing 'self' parameter"
            assert "ctx" in args, "Missing 'ctx' parameter"
            assert "meeting_id" in args, "Missing 'meeting_id' parameter"
            print("  ✓ All required parameters present")

    assert deepinfo_found, "deepinfo method not found"


def check_documentation():
    """Check that documentation exists."""
    import os

    print("\n✓ Checking documentation...")

    doc_file = "docs/DEEPINFO_COMMAND.md"
    assert os.path.exists(doc_file), f"Documentation file not found: {doc_file}"
    print(f"  ✓ Documentation exists: {doc_file}")

    # Check documentation content
    with open(doc_file) as f:
        content = f.read()

    assert "deepinfo" in content.lower(), "Documentation doesn't mention 'deepinfo'"
    assert "meeting_id" in content.lower(), "Documentation doesn't mention 'meeting_id'"
    assert "recording" in content.lower(), "Documentation doesn't mention recordings"
    assert "transcript" in content.lower(), "Documentation doesn't mention transcripts"
    assert "summary" in content.lower(), "Documentation doesn't mention summaries"
    print("  ✓ Documentation content verified")


def main():
    """Run all tests."""
    print("=" * 60)
    print("Testing /deepinfo Command Implementation")
    print("=" * 60)

    try:
        test_service_methods()
        test_sql_models()
        test_command_structure()
        check_documentation()

        print("\n" + "=" * 60)
        print("✅ All tests passed!")
        print("=" * 60)
        print("\nNext steps:")
        print("1. Start the bot with: python main.py")
        print("2. Test the command in Discord: /deepinfo meeting_id:<valid_meeting_id>")
        print("3. Check logs for [DEEPINFO] messages")
        print("4. Verify all embeds are sent correctly")

    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
