% Copyright 2024 The MathWorks, Inc.

if ~isempty(getenv('MWI_CUSTOM_MATLAB_CODE'))
    [mwi_internal_tempFile, mwi_internal_message] = fopen(mwi_internal_user_code_output_file_path, 'w');

    if mwi_internal_tempFile == -1
        % Handle the error if the file cannot be opened
        clear -regexp ^mwi_internal;
        error('Internal Error: Failed to open file: %s', mwi_internal_message);
    else
        try
            % Evaluate the code from the environment variable and capture the output
            mwi_internal_results = evalc(getenv('MWI_CUSTOM_MATLAB_CODE'));
            
            % Write the results to the file
            mwi_internal_bytes = fprintf(mwi_internal_tempFile, " ");
            mwi_internal_bytes = fprintf(mwi_internal_tempFile, mwi_internal_results);
            mwi_internal_status = fclose(mwi_internal_tempFile);
            clear -regexp ^mwi_internal;
        
        catch mwi_internal_MExc
            % If an error occurs during evaluation, write the error message to the file
            mwi_internal_bytes = fprintf(mwi_internal_tempFile, getReport(mwi_internal_MExc, "extended", "hyperlinks", "off"));
            mwi_internal_status = fclose(mwi_internal_tempFile);
            clear -regexp ^mwi_internal;
            error("An error has occurred while executing the given code.")
        end
    end
end