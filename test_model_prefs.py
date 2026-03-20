#!/usr/bin/env python3
"""
Test user model preference functionality
"""

import sys
import tempfile
import os

sys.path.insert(0, '/home/dominik/informatyka/SophiClaw')

import database

def test_model_preferences():
    """Test user model preference storage and retrieval."""
    
    # Create a temporary database for testing
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name
    
    try:
        db = database.Database(db_path)
        db.connect()
        
        print("Testing User Model Preferences")
        print("=" * 50)
        
        # Test 1: No preference set initially
        print("\n1. Testing initial state (no preference)...")
        pref = db.get_user_model_preference(12345)
        if pref is None:
            print("✅ No preference set initially (correct)")
        else:
            print(f"❌ Expected None, got {pref}")
            return False
        
        # Test 2: Set a preference
        print("\n2. Testing setting preference...")
        db.set_user_model_preference(12345, "gemini-3-flash")
        pref = db.get_user_model_preference(12345)
        if pref == "gemini-3-flash":
            print(f"✅ Preference set and retrieved: {pref}")
        else:
            print(f"❌ Expected 'gemini-3-flash', got {pref}")
            return False
        
        # Test 3: Update preference
        print("\n3. Testing updating preference...")
        db.set_user_model_preference(12345, "gemini-3.1-flash-lite")
        pref = db.get_user_model_preference(12345)
        if pref == "gemini-3.1-flash-lite":
            print(f"✅ Preference updated: {pref}")
        else:
            print(f"❌ Expected 'gemini-3.1-flash-lite', got {pref}")
            return False
        
        # Test 4: Different user has different preference
        print("\n4. Testing different users...")
        pref = db.get_user_model_preference(99999)
        if pref is None:
            print("✅ Different user has no preference (correct)")
        else:
            print(f"❌ Expected None for user 99999, got {pref}")
            return False
        
        # Test 5: Set preference for second user
        db.set_user_model_preference(99999, "gemini-2.5-flash")
        pref1 = db.get_user_model_preference(12345)
        pref2 = db.get_user_model_preference(99999)
        if pref1 == "gemini-3.1-flash-lite" and pref2 == "gemini-2.5-flash":
            print("✅ Both users have independent preferences")
        else:
            print(f"❌ Preferences not independent: user1={pref1}, user2={pref2}")
            return False
        
        print("\n🎉 All tests passed!")
        return True
        
    finally:
        # Clean up
        try:
            db.close()
            os.unlink(db_path)
        except:
            pass

if __name__ == "__main__":
    try:
        success = test_model_preferences()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
