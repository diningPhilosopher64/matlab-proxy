import React, { useState, useRef } from "react";

const versionRegex = /^[Rr]\d{4}[ab]$/

function validateInput(matlabVersion) {    
    return versionRegex.test(matlabVersion)
} 

export function MatlabVersionInput({callback}) {
    const [changed, setChanged] = useState(false);
    const [matlabVersionInput, setMatlabVersionInput] = useState("");
    const matlabVersionRef = useRef(null);
    const valid = validateInput(matlabVersionInput)

    const submitForm = (event) => {
        event.preventDefault();
        callback(matlabVersionRef.current.value)
    }

    return <div id="MatlabVersionInput">
    <form onSubmit={submitForm}>
        <div className={`form-group has-feedback ${changed ? (valid ? 'has-success' : 'has-error') : ''}`}>                     
            <p>
                <b>Note</b>: The MATLAB version could not be determined. Enter the version of MATLAB you are attempting to start.
            </p>
            <br/>                   
            <label htmlFor="matlabVersion">MATLAB Version:</label>


            <div className="input-group">
                <input
                type="text"
                className="form-control"
                placeholder={'R20XYb'}
                id="matlabVersion"
                aria-invalid={!valid}
                ref={matlabVersionRef}
                value={matlabVersionInput}
                onChange={event => { setChanged(true); setMatlabVersionInput(event.target.value); }}
                />                        
                <span className="input-group-addon" >
                {valid ? (
                    <span className="glyphicon glyphicon-ok form-control-feedback" style={{ paddingLeft: '8px' }}></span>
                ) : (
                    <span className="glyphicon glyphicon-remove form-control-feedback" style={{ paddingLeft: '8px' }}></span>
                )}
                </span>
            </div>

            <br/><br/>

            <input disabled={!valid} type="submit" id="startMatlabBtn" value="Submit" className="btn btn_color_blue" />
        </div>
    </form>
</div> 
}