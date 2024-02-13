% Copyright 2024 The MathWorks, Inc.

if ~isempty(getenv('MWI_CUSTOM_MATLAB_CODE'))
    mwi_internal_log_file_handle = openLogFile();
    try
        % Evaluate the code from the environment variable and capture the output
        mwi_internal_results = evalc(getenv('MWI_CUSTOM_MATLAB_CODE'));
        % Write the results to the file
        logOutputOrError(mwi_internal_log_file_handle, true, mwi_internal_results, []);
        clear mwi_internal_log_file_handle  mwi_internal_results;
    catch ME
        % Log the error message to the file
        logOutputOrError(mwi_internal_log_file_handle, false, '', ME);
        clear mwi_internal_log_file_handle mwi_internal_results ME;
        error("An error has occurred while executing the given code. For more information check file " + fullfile(getenv('MATLAB_LOG_DIR'), "user_code_output.txt"));
    end

end

function logOutputOrError(file_handle, is_success, user_code_results, ME)
    if is_success
        % Log the successful output of the user code
        fprintf(file_handle, " ");
        fprintf(file_handle, user_code_results);
    else
        % Log the error information
        fprintf(file_handle, 'An error occurred in the following code:\n');
        fprintf(file_handle, getenv('MWI_CUSTOM_MATLAB_CODE'));
        fprintf(file_handle, '\n\nMessage: %s\n', ME.message);
        fprintf(file_handle, '\nError Identifier: %s\n', ME.identifier);
    end
    % Close the file handle
    fclose(file_handle);
end

function file_handle = openLogFile()
    % Construct the path to the output file
    file_path = fullfile(getenv('MATLAB_LOG_DIR'), "user_code_output.txt");
    
    % Open the file for writing
    [file_handle, ~] = fopen(file_path, 'w');
    
    % Check if the file was successfully opened
    if file_handle == -1
        % Handle the error if the file cannot be opened
        ME = MException("", 'The execution of the provided MATLAB code could not be completed.\nInternal Error: Failed to open file: %s', file_path);
        throwAsCaller(ME);
    end
end