% Copyright 2024 The MathWorks, Inc.

% Note:
% Any extra variable we are creating begins with `mwiInternal` to prevent
% potential conflicts with variables created by user code evaluated using evalc.
% Since evalc("user code") is executed in the base workspace, it might create
% variables that could overwrite our internal variables. To avoid polluting the
% user's workspace when MATLAB starts, we ensure to clear any internal variable
% that we create in the base workspace. We do not need to be concerned about
% variables in the function's workspace.

if ~isempty(getenv('MWI_CUSTOM_MATLAB_CODE')) && ~all(isspace(getenv('MWI_CUSTOM_MATLAB_CODE')))
    mwiInternalLogFileHandle = openLogFile();
    try
        % Evaluate the code from the environment variable and capture the output
        mwiInternalResults = evalc(getenv('MWI_CUSTOM_MATLAB_CODE'));
        % Write the results to the file
        logOutputOrError(mwiInternalLogFileHandle, mwiInternalResults);
        clear mwiInternalLogFileHandle mwiInternalResults;
    catch mwiInternalException
        % Log the error message to the file
        logOutputOrError(mwiInternalLogFileHandle, " ", mwiInternalException);
        clear mwiInternalLogFileHandle mwiInternalResults mwiInternalException;
        error("An error has occurred while executing the given code. For more information check file " + fullfile(getenv('MATLAB_LOG_DIR'), "user_code_output.txt"));
    end

end

function logOutputOrError(fileHandle, userCodeResults, mwiInternalException)
    %   Logs the results of the user code execution if successful, otherwise logs the
    %   error information. It then closes the file handle.
    %
    %   Inputs:
    %       fileHandle            - File handle to the log file.
    %       userCodeResults       - String containing the output from the user code.
    %       mwiInternalException  - (Optional) MException object containing error details.
    
    if nargin < 3
        % Log the successful output of the user code
        fprintf(fileHandle, " ");
        fprintf(fileHandle, userCodeResults);
    else
        % Log the error information
        fprintf(fileHandle, 'An error occurred in the following code:\n');
        fprintf(fileHandle, getenv('MWI_CUSTOM_MATLAB_CODE'));
        fprintf(fileHandle, '\n\nMessage: %s\n', mwiInternalException.message);
        fprintf(fileHandle, '\nError Identifier: %s\n', mwiInternalException.identifier);
    end
    % Close the file handle
    fclose(fileHandle);
end

function fileHandle = openLogFile()
    %   Opens a new log file for writing in the
    %   directory specified by the MATLAB_LOG_DIR environment variable. It
    %   returns a file handle to the opened file. If the file cannot be opened,
    %   it throws an error.
    %
    %   Outputs:
    %       fileHandle - File handle to the opened log file.
    
    % Construct the path to the output file
    filePath = fullfile(getenv('MATLAB_LOG_DIR'), "user_code_output.txt");
    
    % Open the file for writing
    [fileHandle, ~] = fopen(filePath, 'w');
    
    % Check if the file was successfully opened
    if fileHandle == -1
        % Handle the error if the file cannot be opened by throwing an error
        ME = MException("", 'The execution of the provided MATLAB code could not be completed.\nInternal Error: Failed to open file: %s', filePath);
        throwAsCaller(ME);
    end
end