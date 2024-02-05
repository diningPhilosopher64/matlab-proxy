% Copyright 2024 The MathWorks, Inc.

if ~isempty( getenv('MWI_CUSTOM_MATLAB_CODE') )
    try
         % Create a directory in the system's temporary directory with a unique name based on the process ID
        mkdir(fullfile(tempdir, 'mw_custom_matlab_code_output'), num2str(feature('getpid')));
    
    catch NoPermissionException 
        % If permission to create the directory is denied, clear variables and raise an error
        clear;
        error(['Failed to create temporary output file because of insufficient permissions at ', tempdir, '. Given code not executed']);
    end
    
    % Open a file for writing the output of user's code in the newly created directory
    mwi_internal_tempFile = fopen(fullfile(tempdir, 'mw_custom_matlab_code_output', num2str(feature('getpid')), 'MWI_CUSTOM_MATLAB_CODE_OUTPUT.txt'), 'w');

    % Check if the file was opened successfully or not
    if mwi_internal_tempFile == -1 
        % If the file could not be opened, attempt to remove the created directory and raise an error
        mwi_internal_status = rmdir(fullfile(tempdir, 'mw_custom_matlab_code_output', num2str(feature('getpid'))), 's');
        
        clear -regexp ^mwi_internal;
        error('Failed to create temporary output file. Given code not executed');
    end
    
    try
        % Evaluate the code from the environment variable and capture the output
        mwi_internal_results = evalc( getenv('MWI_CUSTOM_MATLAB_CODE') );
        
        % Write the results to the file
        mwi_internal_bytes = fprintf(mwi_internal_tempFile, mwi_internal_results);
    
    catch mwi_internal_MExc
        % If an error occurs during evaluation, write the error message to the file
        mwi_internal_bytes = fprintf(mwi_internal_tempFile, mwi_internal_MExc.message);
        
        % Clear all variables except those starting with 'mwi_internal'
        clearvars -except -regexp ^mwi_internal;
    end
    
    mwi_internal_status = fclose(mwi_internal_tempFile); 
    clear -regexp ^mwi_internal;

else
    % If the environment variable is empty, remove the directory if it exists
    mwi_internal_status = rmdir(fullfile(tempdir, 'mw_custom_matlab_code_output', num2str(feature('getpid'))), 's');
    clear;
end