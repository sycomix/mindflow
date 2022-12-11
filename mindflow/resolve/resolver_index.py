from mindflow.utils.response import get_response
from mindflow.utils.exceptions.index_failure import FailureToTrimFiles, IndexGenerationFailure

from typing import List

import os
import json
import chardet
import hashlib

import git

MAX_INDEX_RETRIES = 3


class ResolverIndex:

    def __init__(self, model, verbose: bool = True):
        self.model = model
        self.verbose = verbose

    def log(self, message):
        if self.verbose:
            print(message)

    def get_file_index_description(self, file):
        file_contents = open(file, encoding="utf-8", errors="ignore").read().strip().replace("\n", " ")
        prompt = f"Pretend you are a search engine trying to provide an information rich yet condensed string that can serve as an index for the contents of a file. I want you to respond in as few words as possible while still conveying the contents of this file.\n\n{file_contents}"
        return self._attempt_index_generation(prompt)
    
    def _attempt_index_generation(self, prompt):
        """
        Attempts to generate an index for a file.
        """
        for _ in range(MAX_INDEX_RETRIES):
            try:
                return get_response(self.model, prompt)
            except IndexGenerationFailure:
                pass

        raise IndexGenerationFailure(f"Failed to generate an index after {MAX_INDEX_RETRIES} tries.")
    
    def _get_git_root(self):
        git_repo = git.Repo(os.getcwd(), search_parent_directories=True)
        git_root = git_repo.git.rev_parse("--show-toplevel")
        return git_root

    def _get_index_json(self):
        git_root = self._get_git_root()

        if not os.path.exists(os.path.join(git_root, '.mf')):
            os.mkdir(os.path.join(git_root, '.mf'))
            
        # Open the mf_index.json file in read mode
        try:
            with open(os.path.join(git_root, '.mf/index.json'), 'r') as f:
                index = json.load(f)
        except FileNotFoundError: 
            index = {} 

        return index

    def _write_index_json(self, index_json):
        git_root = self._get_git_root()
        
        # write to the json
        with open(os.path.join(git_root, '.mf/index.json'), "w") as file:
            # Write the contents of the dictionary to the JSON file
            json.dump(index_json, file, indent=2, sort_keys=True)

    def get_file_hash(self, path: str):
        file_bytes = open(path, "rb").read()
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        return file_hash

    def update_file_index(
        self, 
        file_path: str, 
        force_reindex: bool = False,
    ):
        index_json = self._get_index_json()

        file_hash = self.get_file_hash(file_path)

        if not force_reindex:
            data = index_json[file_path]
            should_reindex = data["hash"] != file_hash

            # no need to recalculate if the current hash is already in the index
            if not should_reindex:
                return

        index_description = self.get_file_index_description(file_path)
        index_json[file_path] = {'index': index_description, "hash": file_hash}
        self.log("Index generated for file: ", file_path)

        self._write_index_json(index_json)

    def get_sub_index(self, files: List[str]):
        """Returns a subset of the index for the given files. This is useful 
        for when you have a subdirectory of files that you want to index, but
        you don't want to use the entire repository as context.
        """
        
        index_json = self._get_index_json()

        # important NOTE: we use a None value when keys are missing from the index on purpose
        # this is just in case there was a failure to generate an index for a file, but we still
        # want the context to contain it's filename.
        sub_index = {file: index_json.get(file, None) for file in files}

        return sub_index

    def generate_all_indexes(
        self, 
        files: List[str], 
        force_reindex: bool = False,
        ignore_index_failures: bool = True,
    ) -> dict:
        for filepath in files:
            try:
                self.update_file_index(
                    filepath, 
                    force_reindex=force_reindex,
                )
            except IndexGenerationFailure as failure:
                if ignore_index_failures:
                    self.log(failure.message)
                else:
                    raise failure
