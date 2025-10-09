#!/usr/bin/env python3
"""
Refactored Mapping Review System

This refactored version eliminates code duplication and provides a cleaner,
more maintainable structure for reviewing and mapping medical codes.
"""

import os, json, glob
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Tuple, Union, Iterator
from decouple import Config, RepositoryIni
import requests

def fetch_from_json(filename):
    """
        Load a JSON File
    """
    with open(filename) as json_data:
        return json.load(json_data)

def write_to_json(filename, data):
    """
        Write a dict to a JSON file
    """
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    print(f"Successfully created {filename}")

def get_mapping_files(path_to_mapping_file: str) -> List[str]:
    """
    Get all mapping files that match the pattern, including numbered variants.
    If the file doesn't exist but numbered variants do, return those.
    If the file exists, return just that file.
    """
    # Check if the exact file exists
    if os.path.exists(path_to_mapping_file):
        return [path_to_mapping_file]
    
    # Look for numbered variants (e.g., file_1.json, file_2.json, etc.)
    base_name = os.path.splitext(path_to_mapping_file)[0]
    pattern = f"{base_name}_*.json"
    matching_files = glob.glob(pattern)
    
    if matching_files:
        # Sort by the number in the filename for consistent ordering
        def extract_number(filename):
            import re
            match = re.search(r'_(\d+)\.json$', filename)
            return int(match.group(1)) if match else 0
        
        return sorted(matching_files, key=extract_number)
    
    # If no numbered variants found, return the original path (will be created)
    return [path_to_mapping_file]

def iterate_mapping_files(files: List[str]) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """
    Iterate through mapping files one by one, yielding (file_path, data) tuples.
    This allows processing large datasets without loading everything into memory.
    """
    for file_path in files:
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    yield file_path, data
            except Exception as e:
                print(f"Error loading {file_path}: {e}")
                yield file_path, {}
        else:
            print(f"File {file_path} does not exist, will be created")
            yield file_path, {}

class BaseReviewMixin(ABC):
    """Base class providing common functionality for all review classes."""
    
    def __init__(self, *args, **kwargs):
        self._load_config()
        self._setup_mapping_file(kwargs)
        self.mapping_files = get_mapping_files(self.path_to_mapping_file)
        # For backward compatibility, still load the first file into self.data
        if self.mapping_files:
            # Try to load the first available file
            for file_path in self.mapping_files:
                if os.path.exists(file_path):
                    self.data = fetch_from_json(file_path)
                    break
            else:
                # No files exist yet, start with empty data
                self.data = {}
        else:
            self.data = {}
    
    def _load_config(self):
        """Load configuration from config.ini."""
        self.headers = {
            "authorization": "e50d319f7bec5563c02e958b9977719b",
            "content-type": "application/json"
        }
        
        base_url = "https://newinstance-demo.canvasmedical.com"
        self.url = f"{base_url}/plugin-io/api/coding_lookup/{self.mapping_type}_search"
    
    def _setup_mapping_file(self, kwargs):
        """Setup the mapping file path."""
        if not hasattr(self, 'path_to_mapping_file'):
            if 'path_to_mapping_file' in kwargs:
                self.path_to_mapping_file = kwargs['path_to_mapping_file']
            else:
                self.path_to_mapping_file = self._get_default_mapping_file()
    
    @abstractmethod
    def _get_default_mapping_file(self) -> str:
        """Return the default mapping file path for this review type."""
        pass
    
    def _make_api_request(self, params: Dict[str, str]) -> Dict[str, Any]:
        """Make an API request with error handling."""
        response = requests.get(self.url, headers=self.headers, params=params)
        if response.status_code != 200:
            raise Exception(f"API request failed: {response.text}")
        return response.json()
    
    def _save_mapping(self):
        """Save the current mapping data to file."""
        # If we're in file-by-file mode, save to the current file
        if hasattr(self, '_current_file_path'):
            write_to_json(self._current_file_path, self.data)
        else:
            # Fallback to original behavior
            write_to_json(self.path_to_mapping_file, self.data)
    
    def _get_user_input(self, prompt: str, valid_options: Optional[List[str]] = None) -> str:
        """Get user input with validation."""
        while True:
            user_input = input(prompt).strip()
            if valid_options is None or user_input in valid_options:
                return user_input
            print(f"Invalid input. Please choose from: {', '.join(valid_options)}")
    
    def _display_options(self, options: List[Any], display_key: str = 'text') -> Dict[str, Any]:
        """Display options and return a mapping of choice numbers to options."""
        print()

        if not options:
            print('⚠️  No options found for this term\n')
            return {}
        
        choice_map = {}
        for i, option in enumerate(options, 1):
            # For allergies, show concept_type: display format
            if self.mapping_type == 'allergy':
                concept_type = option.get('concept_type', 'Unknown')
                display = option.get('display', 'Unknown')
                display_text = f"{concept_type}: {display}"
            else:
                # For other types, use the standard display_key
                display_text = option.get(display_key, str(option))
            
            print(f"{i}) {display_text}")
            choice_map[str(i)] = option
        
        print()
        return choice_map
    
    def _validate_multiple_mapping(self, mapping_result: Dict[str, List]) -> bool:
        """Validate that a multiple mapping result is valid and contains items."""
        if not mapping_result:
            return False
        if 'multiple' not in mapping_result:
            return False
        if not mapping_result['multiple']:
            return False
        return True

    def _get_special_options(self) -> Dict[str, Dict[str, Any]]:
        """Return special options for this review type. Override in subclasses."""
        return {}

    def _handle_special_choice(self, choice: str, key: str) -> bool:
        """Handle special choice options. Override in subclasses."""
        return False

    def _get_display_key(self) -> str:
        """Return the key to use for displaying options. Override in subclasses."""
        return 'text'

    def _is_item_completed(self, item: Any) -> bool:
        """Check if an item is already completed. Override in subclasses."""
        return bool(item and isinstance(item, dict))

    def _map_codes(self, ls: Optional[List[str]], search_params: Dict[str, str], code_param: str):
        """Common mapping logic for all review types."""
        _map = fetch_from_json(self.path_to_mapping_file)
        
        if ls is not None:
            for item in ls:
                if item.lower() not in _map:
                    _map[item.lower()] = []
        
        total = len(_map)
        
        for i, (key, item) in enumerate(_map.items()):
            print(f'\n{key} ({i+1}/{total})')
            
            if item:
                print('Already mapped, skipping')
                continue
            
            name, code = key.split('|')
            options = []
            
            # Clean up name and split into parts for partial matching
            name = name.replace(':', '')
            name_list = name.split(' ')
            found_coding = None
            
            # For medications, we can search by both name AND code together
            if self.mapping_type == 'medication' and code and name:
                try:
                    # First try: search by both RxNorm code AND text together
                    response_data = self._make_api_request({"rxnorm_code": code, "text": name})
                    results = response_data.get('results', [])
                    
                    if len(results) == 1:
                        _map[key] = results[0]
                        continue
                    elif len(results) > 1:
                        # Add all results to options for user choice
                        for result in results:
                            if result not in options:
                                options.append(result)
                except Exception as e:
                    print(f"Error searching by code + text: {e}")
            
            # Search by code only
            if code:
                try:
                    response_data = self._make_api_request({code_param: code})
                    results = response_data.get('results', [])
                    
                    if len(results) == 1:
                        _map[key] = results[0]
                        continue
                    elif len(results) > 1:
                        # Try to find exact match by name
                        found = False
                        for result in results:
                            if self._is_exact_match(result, name):
                                _map[key] = result
                                found = True
                                break
                        
                        if not found:
                            # Add all results to options
                            for result in results:
                                if result not in options:
                                    options.append(result)
                    # Note: No else clause here - we want to fall through to text search
                except Exception as e:
                    print(f"Error searching by code: {e}")
            
            # Search by text if no code match found (or if code search failed)
            if not _map.get(key) and name:
                try:
                    # Try different text search strategies
                    self._search_by_text(_map, key, name, options, search_params)
                except Exception as e:
                    print(f"Error searching by text: {e}")
            
            # Set options if no direct match found
            if not _map.get(key):
                _map[key] = options
                    
        # Save sorted results
        sorted_items = sorted(_map.items(), key=lambda kv: kv[0].lower())
        ordered = dict(sorted_items)
        write_to_json(self.path_to_mapping_file, ordered)

    def _is_exact_match(self, result: Dict[str, Any], name: str) -> bool:
        """Check if a result exactly matches the name."""
        display_text = result.get('text', result.get('display', ''))
        return display_text.lower() == name.lower()
    
    def _search_by_text(self, _map: Dict, key: str, name: str, options: List, search_params: Dict[str, str]):
        """Search by text using different strategies."""
        # Try full name first
        response_data = self._make_api_request({**search_params, "text": name})
        results = response_data.get('results', [])
        
        if len(results) == 1:
            if self._is_exact_match(results[0], name):
                _map[key] = results[0]
                return
            elif results[0] not in options:
                options.append(results[0])
        elif len(results) > 1:
            for result in results:
                if self._is_exact_match(result, name):
                    _map[key] = result
                    return
                elif result not in options:
                    options.append(result)
        
        # Only do partial name matching for medications (where it's most useful)
        if self.mapping_type == 'medication':
            # Try partial name matches (especially useful for medications)
            name_parts = name.split()
            for i in reversed(range(len(name_parts))):
                partial_name = " ".join(name_parts[:i+1]).strip()
                if partial_name:
                    try:
                        response_data = self._make_api_request({**search_params, "text": partial_name})
                        results = response_data.get('results', [])
                        
                        for result in results:
                            if self._is_exact_match(result, name):
                                _map[key] = result
                                return
                            elif result not in options:
                                options.append(result)
                        if len(options):
                            return
                    except Exception as e:
                        print(f"Error searching with partial name '{partial_name}': {e}")
                        continue

    def _review_base(self, skip_done: bool = True, **kwargs):
        """Base review functionality shared across all review types."""
        total = len(self.data)
        
        for i, (key, item) in enumerate(dict(self.data).items()):
            print('-' * 56)
            print(f'Looking at row {i+1}/{total}')
            
            if self._is_item_completed(item):
                if not skip_done:
                    print(f"Already mapped {key} to {item}\n")
                continue
            
            print(f"\n{key}")

            search_results = item  # Start with the original item
            
            while True:
                # Always call _display_options to show available options (or "No options found")
                options = self._display_options(item, self._get_display_key())
                
                # Build prompt with special options
                special_options = self._get_special_options()
                special_prompt = ""
                if special_options:
                    special_prompt = ", ".join([f'"{opt}" for {desc}' for opt, desc in special_options.items()])
                    special_prompt = f", {special_prompt}"
                
                prompt = (f'What do you want to map "{key}" to?\n'
                         f'Pick a number, "0" to not map into Canvas{special_prompt}, "m" for multiple, "s" to skip for now, or type to search: ')
                
                choice = input(prompt).strip()
                
                if choice == '0':
                    self.data.pop(key)
                    self._save_mapping()
                    break
                if choice == 's':
                    break
                elif choice in special_options:
                    if self._handle_special_choice(choice, key):
                        break
                elif choice == 'm':
                    mapping_result = self._handle_multiple_mapping(key)
                    if self._validate_multiple_mapping(mapping_result):
                        self.data[key] = mapping_result
                        self._save_mapping()
                        print(f"💾 Saved multiple mapping for '{key}'")
                    else:
                        print(f"⚠️ Multiple mapping for '{key}' was not completed or was empty")
                    break
                elif choice in options:
                    self.data[key] = options[choice]
                    self._save_mapping()
                    break
                else:
                    # Search for new options
                    try:
                        response_data = self._make_api_request({"text": choice})
                        search_results = response_data.get('results', [])
                    except Exception as e:
                        print(f"Error searching: {e}")
                        item = []
        
        print('DONE!!')

    def _review_file_by_file(self, skip_done: bool = True, **kwargs):
        """
        Review mapping files one by one without loading all into memory.
        This is memory-efficient for large datasets.
        """
        total_files = len(self.mapping_files)
        print(f"Processing {total_files} mapping file(s)...")
        
        for file_idx, (file_path, data) in enumerate(iterate_mapping_files(self.mapping_files)):
            print(f"\n{'='*60}")
            print(f"Processing file {file_idx + 1}/{total_files}: {os.path.basename(file_path)}")
            print(f"{'='*60}")
            
            if not data:
                print(f"No data in {file_path}, skipping...")
                continue
            
            # Temporarily replace self.data with current file's data
            original_data = self.data
            self.data = data
            
            # Set the current file path so _save_mapping knows where to save
            self._current_file_path = file_path
            
            # Use the existing review_base method
            self._review_base(skip_done=skip_done, **kwargs)
            
            # Clean up the current file path
            if hasattr(self, '_current_file_path'):
                delattr(self, '_current_file_path')
            
            # Restore original data
            self.data = original_data
        
        print('\n🎉 All files processed!')

    def _handle_multiple_mapping(self, key: str) -> Dict[str, List]:
        """Handle mapping a single key to multiple items."""
        print(f'\nYou are choosing to map "{key}" as multiple different records\n')
        mapping = {'multiple': []}
        
        while True:
            search_term = input('\nType a term to search for, "done" when finished, or "abort" to skip: ')
            
            if search_term.lower() == 'done':
                if mapping['multiple']:
                    print(f"✅ Successfully mapped '{key}' to {len(mapping['multiple'])} items")
                else:
                    print("⚠️ Warning: No items were mapped. Consider using a different approach.")
                return mapping
            elif search_term.lower() == 'abort':
                print("❌ Multiple mapping aborted")
                return mapping
            
            # Search for options using the user's search term
            try:
                # Generate search parameters based on the data type and user input
                search_params = {"text": search_term}                
                response_data = self._make_api_request(search_params)
                search_results = response_data.get('results', [])
                
                if not search_results:
                    print("No results found for that search term.")
                    continue
                
                choice_map = self._display_options(search_results)
                if not choice_map:
                    continue
                
                choice = self._get_user_input('Pick a number to map to or "0" to ignore all options: ')
                if choice in choice_map:
                    mapping['multiple'].append(choice_map[choice])
                    print(f"✅ Added: {choice_map[choice].get('text', choice_map[choice].get('display', 'Unknown'))}")
                    
            except Exception as e:
                print(f"Error searching for '{search_term}': {e}")
        
        return mapping


class AllergyReview(BaseReviewMixin):
    """Review and map allergy codes."""
    
    def __init__(self, *args, **kwargs):
        if hasattr(self, 'allergy_map_file'):
            self.path_to_mapping_file = self.allergy_map_file
        
        self.mapping_type = 'allergy'
        super().__init__(*args, **kwargs)
    
    def _get_default_mapping_file(self) -> str:
        return "allergy_coding_map.json"
    
    def _get_generic_option(self) -> Dict[str, str]:
        """Return the generic allergy option."""
        return {
            "display": "No Allergy Information Available",
            "concept_type": "allergy group",
            "concept_id": "143",
            "code": "1-143",
            "system": "http://www.fdbhealth.com/"
        }

    def _get_special_options(self) -> Dict[str, str]:
        """Return special options for allergy review."""
        return {"-1": "generic"}

    def _handle_special_choice(self, choice: str, key: str) -> bool:
        """Handle special choice options for allergies."""
        if choice == "-1":
            self.data[key] = self._get_generic_option()
            self._save_mapping()
            return True
        return False

    def _is_item_completed(self, item: Any) -> bool:
        """Check if an allergy item is already completed."""
        return bool(item and isinstance(item, dict))
    
    def review(self, skip_done: bool = True):
        """Review and map allergy codes interactively."""
        self._review_base(skip_done=skip_done)
    
    def review_file_by_file(self, skip_done: bool = True):
        """Review and map allergy codes file by file (memory-efficient)."""
        self._review_file_by_file(skip_done=skip_done)
    
    def map(self, ls: Optional[List[str]] = None):
        """Map allergy codes using RxNorm codes and text search."""
        self._map_codes(ls, search_params={"text": ""}, code_param="rxnorm_code")


class MedicationReview(BaseReviewMixin):
    """Review and map medication codes."""
    
    def __init__(self, *args, **kwargs):
        if hasattr(self, 'medication_map_file'):
            self.path_to_mapping_file = self.medication_map_file
        
        self.mapping_type = 'medication'
        super().__init__(*args, **kwargs)
    
    def _get_default_mapping_file(self) -> str:
        return "medication_coding_map.json"

    def _get_special_options(self) -> Dict[str, str]:
        """Return special options for medication review."""
        return {"-1": "unstructured"}

    def _handle_special_choice(self, choice: str, key: str) -> bool:
        """Handle special choice options for medications."""
        if choice == "-1":
            self.data[key] = "unstructured"
            self._save_mapping()
            return True
        return False

    def _is_item_completed(self, item: Any) -> bool:
        """Check if a medication item is already completed."""
        return bool(item and (isinstance(item, dict) or item == "unstructured"))
    
    def review(self, skip_done: bool = True, mapping_csv: bool = False):
        """Review and map medication codes interactively."""
        self._review_base(skip_done=skip_done)
    
    def review_file_by_file(self, skip_done: bool = True):
        """Review and map medication codes file by file (memory-efficient)."""
        self._review_file_by_file(skip_done=skip_done)
    
    def map(self, ls: Optional[List[str]] = None):
        """Map medication codes using RxNorm codes and text search."""
        self._map_codes(ls, search_params={"text": ""}, code_param="rxnorm_code")


class ConditionReview(BaseReviewMixin):
    """Review and map condition codes."""
    
    def __init__(self, *args, **kwargs):
        if hasattr(self, 'condition_map_file'):
            self.path_to_mapping_file = self.condition_map_file
        
        self.mapping_type = 'condition'
        super().__init__(*args, **kwargs)
    
    def _get_default_mapping_file(self) -> str:
        return "condition_coding_map.json"

    def _get_special_options(self) -> Dict[str, str]:
        """Return special options for condition review."""
        return {}  # No special options for conditions yet

    def _handle_special_choice(self, choice: str, key: str) -> bool:
        """Handle special choice options for conditions."""
        return False  # No special choices for conditions yet

    def _is_item_completed(self, item: Any) -> bool:
        """Check if a condition item is already completed."""
        return bool(item and isinstance(item, dict))
    
    def review(self, skip_done: bool = True):
        """Review and map condition codes interactively."""
        self._review_base(skip_done=skip_done)
    
    def review_file_by_file(self, skip_done: bool = True):
        """Review and map condition codes file by file (memory-efficient)."""
        self._review_file_by_file(skip_done=skip_done)
    
    def map(self, ls: Optional[List[str]] = None):
        """Map condition codes using ICD-10 codes and text search."""
        self._map_codes(ls, search_params={"text": ""}, code_param="icd10_code")
