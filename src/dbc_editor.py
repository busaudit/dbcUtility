#!/usr/bin/env python3

"""
DBC Editor Module
Supports loading, editing, and saving CAN/J1939 DBC files.
"""

import os
import logging
import json
import shutil
from typing import Dict, List, Any, Optional
import cantools

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DBCEditorError(Exception):
    pass

class DBCEditor:
    def __init__(self):
        self.db = None
        self.file_path = None
        self._original_data = None
        self._modified_data = None

    def create_new_dbc(self) -> Dict[str, Any]:
        """
        Create a new empty DBC file structure.
        Returns a dict with empty messages list.
        """
        try:
            self.db = cantools.database.Database()
            self.file_path = None
            self._original_data = {'messages': []}
            self._modified_data = {'messages': []}
            
            logger.info("Created new empty DBC file")
            return self._original_data
            
        except Exception as e:
            logger.error(f"Failed to create new DBC: {e}")
            raise DBCEditorError(f"Failed to create new DBC: {e}")

    def load_dbc_file(self, file_path: str) -> Dict[str, Any]:
        """
        Load and parse a DBC file using cantools.
        Returns a dict with messages and signals.
        """
        try:
            if not os.path.exists(file_path):
                raise DBCEditorError(f"DBC file not found: {file_path}")
            if not file_path.lower().endswith('.dbc'):
                raise DBCEditorError("File must have .dbc extension")
            
            self.file_path = file_path
            self.db = cantools.database.load_file(file_path)
            messages_data = []
            
            for msg in self.db.messages:
                signals_data = []
                for sig in msg.signals:
                    # Safely get signal properties with defaults
                    try:
                        scale = getattr(sig, 'scale', 1.0)
                        if hasattr(scale, '__call__'):  # If scale is a callable
                            scale = scale()
                    except:
                        scale = 1.0
                    
                    try:
                        offset = getattr(sig, 'offset', 0.0)
                        if hasattr(offset, '__call__'):  # If offset is a callable
                            offset = offset()
                    except:
                        offset = 0.0
                    
                    try:
                        minimum = getattr(sig, 'minimum', None)
                        if hasattr(minimum, '__call__'):  # If minimum is a callable
                            minimum = minimum()
                    except:
                        minimum = None
                    
                    try:
                        maximum = getattr(sig, 'maximum', None)
                        if hasattr(maximum, '__call__'):  # If maximum is a callable
                            maximum = maximum()
                    except:
                        maximum = None
                    
                    signals_data.append({
                        'name': sig.name,
                        'start_bit': getattr(sig, 'start', 0),
                        'length': getattr(sig, 'length', 1),
                        'is_signed': getattr(sig, 'is_signed', False),
                        'scale': scale,
                        'offset': offset,
                        'minimum': minimum,
                        'maximum': maximum,
                        'unit': getattr(sig, 'unit', '') or '',
                        'receivers': [str(r) for r in getattr(sig, 'receivers', [])],
                        'comments': self._extract_comment_text(getattr(sig, 'comments', '')) if getattr(sig, 'comments', '') else ''
                    })
                
                messages_data.append({
                    'name': msg.name,
                    'frame_id': msg.frame_id,
                    'length': msg.length,
                    'senders': [str(s) for s in msg.senders],
                    'signals': signals_data,
                    'comments': self._extract_comment_text(msg.comment) if msg.comment else ''
                })
            
            self._original_data = {'messages': messages_data}
            # Create a proper deep copy for modified data
            self._modified_data = {
                'messages': [
                    {
                        'name': msg['name'],
                        'frame_id': msg['frame_id'],
                        'length': msg['length'],
                        'senders': msg['senders'].copy(),
                        'signals': [
                            {
                                'name': sig['name'],
                                'start_bit': sig['start_bit'],
                                'length': sig['length'],
                                'is_signed': sig['is_signed'],
                                'scale': sig['scale'],
                                'offset': sig['offset'],
                                'minimum': sig['minimum'],
                                'maximum': sig['maximum'],
                                'unit': sig['unit'],
                                'receivers': sig['receivers'].copy(),
                                'comments': sig['comments']
                            }
                            for sig in msg['signals']
                        ],
                        'comments': msg['comments']
                    }
                    for msg in messages_data
                ]
            }
            
            # Verify the copy is independent
            logger.info(f"Original data has {len(self._original_data['messages'])} messages")
            logger.info(f"Modified data has {len(self._modified_data['messages'])} messages")
            
            logger.info(f"Loaded DBC file: {file_path} ({len(messages_data)} messages)")
            return self._original_data
            
        except Exception as e:
            logger.error(f"Failed to load DBC: {e}")
            raise DBCEditorError(f"Failed to load DBC: {e}")

    def get_data(self) -> Dict[str, Any]:
        return self._modified_data if self._modified_data else {}

    def add_message(self, message: Dict[str, Any]) -> None:
        if not self._modified_data:
            self._modified_data = {'messages': []}
        self._modified_data['messages'].append(message)

    def update_message(self, idx: int, message: Dict[str, Any]) -> None:
        if not self._modified_data or idx >= len(self._modified_data['messages']):
            raise DBCEditorError("Invalid message index")
        self._modified_data['messages'][idx] = message
    
    def duplicate_message(self, idx: int) -> int:
        """
        Duplicate a message at idx and append it to the list.
        Returns the new message index.
        """
        if not self._modified_data or idx < 0 or idx >= len(self._modified_data['messages']):
            raise DBCEditorError("Invalid message index")
        original = self._modified_data['messages'][idx]
        new_message = {
            'name': original['name'],
            'frame_id': original['frame_id'],
            'length': original['length'],
            'senders': list(original.get('senders', [])),
            'signals': [dict(sig) for sig in original.get('signals', [])],
            'comments': original.get('comments', '')
        }
        # Ensure unique name by appending "_1", "_2", etc.
        base_name = original['name']
        candidate = f"{base_name}_1"
        suffix = 2
        existing_names = {m['name'] for m in self._modified_data['messages']}
        while candidate in existing_names:
            candidate = f"{base_name}_{suffix}"
            suffix += 1
        new_message['name'] = candidate
        self._modified_data['messages'].append(new_message)
        return len(self._modified_data['messages']) - 1
    
    def move_message_up(self, idx: int) -> int:
        """
        Move message at idx up by one position.
        Returns the new index.
        """
        if not self._modified_data or idx <= 0 or idx >= len(self._modified_data['messages']):
            raise DBCEditorError("Invalid message move operation")
        msgs = self._modified_data['messages']
        msgs[idx - 1], msgs[idx] = msgs[idx], msgs[idx - 1]
        return idx - 1
    
    def move_message_down(self, idx: int) -> int:
        """
        Move message at idx down by one position.
        Returns the new index.
        """
        if not self._modified_data or idx < 0 or idx >= len(self._modified_data['messages']) - 1:
            raise DBCEditorError("Invalid message move operation")
        msgs = self._modified_data['messages']
        msgs[idx + 1], msgs[idx] = msgs[idx], msgs[idx + 1]
        return idx + 1

    def delete_message(self, idx: int) -> None:
        if not self._modified_data or idx >= len(self._modified_data['messages']):
            raise DBCEditorError("Invalid message index")
        del self._modified_data['messages'][idx]

    def add_signal(self, msg_idx: int, signal: Dict[str, Any]) -> None:
        if not self._modified_data or msg_idx >= len(self._modified_data['messages']):
            raise DBCEditorError("Invalid message index")
        self._modified_data['messages'][msg_idx]['signals'].append(signal)
        logger.info(f"Added signal '{signal['name']}' to message {msg_idx}")

    def update_signal(self, msg_idx: int, sig_idx: int, signal: Dict[str, Any]) -> None:
        if not self._modified_data or msg_idx >= len(self._modified_data['messages']):
            raise DBCEditorError("Invalid message index")
        if sig_idx >= len(self._modified_data['messages'][msg_idx]['signals']):
            raise DBCEditorError("Invalid signal index")
        self._modified_data['messages'][msg_idx]['signals'][sig_idx] = signal
        logger.info(f"Updated signal '{signal['name']}' in message {msg_idx}")
    
    def duplicate_signal(self, msg_idx: int, sig_idx: int) -> int:
        """
        Duplicate signal at sig_idx within message msg_idx.
        Returns the index of the newly created signal.
        """
        if not self._modified_data or msg_idx < 0 or msg_idx >= len(self._modified_data['messages']):
            raise DBCEditorError("Invalid message index")
        signals = self._modified_data['messages'][msg_idx]['signals']
        if sig_idx < 0 or sig_idx >= len(signals):
            raise DBCEditorError("Invalid signal index")
        original = signals[sig_idx]
        new_signal = dict(original)
        # Ensure unique name by appending "_1", "_2", etc.
        base_name = original['name']
        candidate = f"{base_name}_1"
        suffix = 2
        existing_names = {s['name'] for s in signals}
        while candidate in existing_names:
            candidate = f"{base_name}_{suffix}"
            suffix += 1
        new_signal['name'] = candidate
        signals.append(new_signal)
        return len(signals) - 1
    
    def move_signal_up(self, msg_idx: int, sig_idx: int) -> int:
        """
        Move signal at sig_idx up within message msg_idx.
        Returns new signal index.
        """
        if (not self._modified_data or
            msg_idx < 0 or msg_idx >= len(self._modified_data['messages'])):
            raise DBCEditorError("Invalid message index")
        signals = self._modified_data['messages'][msg_idx]['signals']
        if sig_idx <= 0 or sig_idx >= len(signals):
            raise DBCEditorError("Invalid signal move operation")
        signals[sig_idx - 1], signals[sig_idx] = signals[sig_idx], signals[sig_idx - 1]
        return sig_idx - 1
    
    def move_signal_down(self, msg_idx: int, sig_idx: int) -> int:
        """
        Move signal at sig_idx down within message msg_idx.
        Returns new signal index.
        """
        if (not self._modified_data or
            msg_idx < 0 or msg_idx >= len(self._modified_data['messages'])):
            raise DBCEditorError("Invalid message index")
        signals = self._modified_data['messages'][msg_idx]['signals']
        if sig_idx < 0 or sig_idx >= len(signals) - 1:
            raise DBCEditorError("Invalid signal move operation")
        signals[sig_idx + 1], signals[sig_idx] = signals[sig_idx], signals[sig_idx + 1]
        return sig_idx + 1

    def delete_signal(self, msg_idx: int, sig_idx: int) -> None:
        if not self._modified_data or msg_idx >= len(self._modified_data['messages']):
            raise DBCEditorError("Invalid message index")
        if sig_idx >= len(self._modified_data['messages'][msg_idx]['signals']):
            raise DBCEditorError("Invalid signal index")
        signal_name = self._modified_data['messages'][msg_idx]['signals'][sig_idx]['name']
        del self._modified_data['messages'][msg_idx]['signals'][sig_idx]
        logger.info(f"Deleted signal '{signal_name}' from message {msg_idx}")

    def save_dbc_file(self, file_path: Optional[str] = None) -> None:
        """
        Save the modified DBC data to a file using cantools.
        Creates a backup of the original file before saving.
        """
        try:
            if file_path is None:
                file_path = self.file_path
            if not file_path:
                raise DBCEditorError("No file path specified for saving")
            
            # Create backup of original file
            if os.path.exists(file_path):
                backup_path = file_path + '.backup'
                shutil.copy2(file_path, backup_path)
                logger.info(f"Created backup: {backup_path}")
            
            # Rebuild cantools database from modified data
            db = cantools.database.Database()
            
            for msg in self._modified_data['messages']:
                signals = []
                for sig in msg['signals']:
                    # Create signal with safe property access
                    signal = cantools.database.can.Signal(
                        name=sig['name'],
                        start=sig['start_bit'],
                        length=sig['length'],
                        is_signed=sig['is_signed'],
                        receivers=sig['receivers']
                    )
                    
                    # Set additional properties after creation
                    signal.scale = sig['scale']
                    signal.offset = sig['offset']
                    # Handle None values for minimum and maximum
                    signal.minimum = sig['minimum'] if sig['minimum'] is not None else None
                    signal.maximum = sig['maximum'] if sig['maximum'] is not None else None
                    signal.unit = sig['unit']
                    
                    # Set comment if available
                    if sig.get('comments'):
                        signal.comment = sig['comments']
                    
                    signals.append(signal)
                
                # Create message
                message = cantools.database.can.Message(
                    frame_id=msg['frame_id'],
                    name=msg['name'],
                    length=msg['length'],
                    senders=msg['senders'],
                    signals=signals,
                    is_extended_frame=msg['frame_id'] > 0x7FF  # Use extended frame for IDs > 11 bits
                )
                
                # Set comment if available
                if msg.get('comments'):
                    message.comment = msg['comments']
                
                db.messages.append(message)
            
            # Write to file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(db.as_dbc_string())
            
            # Update original data to reflect saved state
            self._original_data = {'messages': [dict(m) for m in self._modified_data['messages']]}
            
            # Clean up backup file after successful save
            self._cleanup_backup_file(file_path)
            
            logger.info(f"Saved DBC file: {file_path}")
            
        except Exception as e:
            logger.error(f"Failed to save DBC: {e}")
            raise DBCEditorError(f"Failed to save DBC: {e}")

    def has_changes(self) -> bool:
        """Improved change detection using deep comparison."""
        if not self._original_data or not self._modified_data:
            return False
        
        try:
            # Compare message counts first
            orig_msg_count = len(self._original_data['messages'])
            mod_msg_count = len(self._modified_data['messages'])
            
            if orig_msg_count != mod_msg_count:
                logger.info(f"Message count changed: {orig_msg_count} -> {mod_msg_count}")
                return True
            
            # Compare each message and its signals
            for i, (orig_msg, mod_msg) in enumerate(zip(self._original_data['messages'], self._modified_data['messages'])):
                # Compare message properties
                if orig_msg['name'] != mod_msg['name'] or orig_msg['frame_id'] != mod_msg['frame_id']:
                    logger.info(f"Message {i} properties changed")
                    return True
                
                # Compare signal counts
                orig_sig_count = len(orig_msg['signals'])
                mod_sig_count = len(mod_msg['signals'])
                
                if orig_sig_count != mod_sig_count:
                    logger.info(f"Message {i} signal count changed: {orig_sig_count} -> {mod_sig_count}")
                    return True
                
                # Compare each signal
                for j, (orig_sig, mod_sig) in enumerate(zip(orig_msg['signals'], mod_msg['signals'])):
                    if orig_sig != mod_sig:
                        logger.info(f"Signal {j} in message {i} changed")
                        return True
            
            logger.info("No changes detected in DBC data")
            return False
            
        except Exception as e:
            logger.warning(f"Change detection failed: {e}")
            # Fallback to JSON comparison
            try:
                orig_json = json.dumps(self._original_data, sort_keys=True, default=str)
                mod_json = json.dumps(self._modified_data, sort_keys=True, default=str)
                return orig_json != mod_json
            except:
                # Final fallback to simple comparison
                return self._original_data != self._modified_data

    def get_changes_summary(self) -> Dict[str, Any]:
        """Get a detailed summary of changes made to the DBC file."""
        if not self.has_changes():
            return {"has_changes": False}
        
        try:
            orig = {m['name']: m for m in self._original_data['messages']}
            mod = {m['name']: m for m in self._modified_data['messages']}
            
            added_messages = [n for n in mod if n not in orig]
            deleted_messages = [n for n in orig if n not in mod]
            modified_messages = []
            added_signals = []
            deleted_signals = []
            modified_signals = []
            
            # Check for modified messages and signal changes
            for msg_name in mod:
                if msg_name in orig:
                    orig_msg = orig[msg_name]
                    mod_msg = mod[msg_name]
                    
                    # Check if message itself is modified
                    if mod_msg != orig_msg:
                        modified_messages.append(msg_name)
                        
                        # Check signal changes within this message
                        orig_signals = {s['name']: s for s in orig_msg.get('signals', [])}
                        mod_signals = {s['name']: s for s in mod_msg.get('signals', [])}
                        
                        # Added signals
                        for sig_name in mod_signals:
                            if sig_name not in orig_signals:
                                added_signals.append(f"{msg_name}.{sig_name}")
                        
                        # Deleted signals
                        for sig_name in orig_signals:
                            if sig_name not in mod_signals:
                                deleted_signals.append(f"{msg_name}.{sig_name}")
                        
                        # Modified signals
                        for sig_name in mod_signals:
                            if sig_name in orig_signals and mod_signals[sig_name] != orig_signals[sig_name]:
                                modified_signals.append(f"{msg_name}.{sig_name}")
            
            return {
                "has_changes": True,
                "added_messages": added_messages,
                "deleted_messages": deleted_messages,
                "modified_messages": modified_messages,
                "added_signals": added_signals,
                "deleted_signals": deleted_signals,
                "modified_signals": modified_signals
            }
        except Exception as e:
            logger.warning(f"Changes summary failed: {e}")
            return {"has_changes": True, "error": str(e)}

    def _extract_comment_text(self, comment_obj, max_depth=5):
        """Extract clean comment text from potentially malformed comment objects."""
        if not comment_obj:
            return ''
        
        # If it's already a string, return it
        if isinstance(comment_obj, str):
            return comment_obj
        
        # If it's a dict, try to extract the actual comment text
        if isinstance(comment_obj, dict):
            return self._extract_comment_from_dict(comment_obj, max_depth)
        
        # For any other type, convert to string
        return str(comment_obj)
    
    def _extract_comment_from_dict(self, comment_dict, max_depth):
        """Recursively extract comment text from nested dictionary."""
        if not isinstance(comment_dict, dict) or max_depth <= 0:
            return str(comment_dict)
        
        # Look for string values
        for key, value in comment_dict.items():
            if isinstance(value, str):
                # Clean up the string - remove escape sequences and None references
                cleaned = value.replace('\\\'', "'").replace('\\"', '"')
                # Remove None key references and extra quotes
                cleaned = cleaned.replace('{None: ', '').replace('}', '')
                # Remove extra quotes at the beginning and end
                cleaned = cleaned.strip("'\"")
                # Remove encoding artifacts
                cleaned = cleaned.replace('ÃƒÆÃ†â€™Ãƒâ€šÃ‚Â¢ÃƒÆÃ‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆÃ¢â‚¬Å¡Ãƒâ€šÃ‚Â¦', '')
                return cleaned
            elif isinstance(value, dict):
                result = self._extract_comment_from_dict(value, max_depth - 1)
                if result and result != str(value):
                    return result
        
        return str(comment_dict)

    def reset_changes(self) -> None:
        """Reset all changes back to the original state."""
        if self._original_data:
            self._modified_data = {'messages': [dict(m) for m in self._original_data['messages']]}

    def _cleanup_backup_file(self, file_path: str) -> None:
        """Delete the backup file for the given DBC file."""
        try:
            backup_path = file_path + '.backup'
            if os.path.exists(backup_path):
                os.remove(backup_path)
                logger.info(f"Cleaned up backup file: {backup_path}")
        except Exception as e:
            logger.warning(f"Could not delete backup file {backup_path}: {e}")

    def cleanup_all_backups(self) -> None:
        """Clean up all backup files for loaded DBC files."""
        if self.file_path:
            self._cleanup_backup_file(self.file_path) 