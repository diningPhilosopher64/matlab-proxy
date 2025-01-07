// Copyright 2023-2024 The MathWorks, Inc/
import React, { useState } from "react";
import { useSelector, useDispatch } from "react-redux";
import { MatlabVersionInput } from "./MatlabVersionInput";
import {
    selectMatlabVersionOnPath,
} from "../../selectors";
import {
    fetchSetLicensing
} from "../../actionCreators";
import "./ExistingLicense.css";

function ExistingLicense () {
    const dispatch = useDispatch();
    const matlabVersionOnPath = useSelector(selectMatlabVersionOnPath);
    const [isExistingLicenseFormSubmitted, setExistingLicenseFormSubmitted] = useState(false);    
    

    function submitForm (event) {
        event.preventDefault();
        setExistingLicenseFormSubmitted(true);
    }

    const setLicensingInfo = (userProvidedMatlabVersion) => {
        dispatch(fetchSetLicensing({
            "type": "existing_license",
            "matlabVersion": userProvidedMatlabVersion
        }));
    };

    const existingLicenseForm = (
        <div id="ExistingLicense">
            <form onSubmit={submitForm}>
                <div className='form-group'>
                    <p>
                        <b>Note</b>: Choose this option if you already have an activated MATLAB license. This option allows you to run MATLAB on your host machine without providing additional licensing information.
                    </p>
                    <br/>
                    <input type="submit" id="existingLicenseSubmit" value="Start MATLAB" className="btn btn_color_blue" />
                </div>
            </form>
        </div>
    );

    if(isExistingLicenseFormSubmitted && !matlabVersionOnPath){
       return <MatlabVersionInput callback={setLicensingInfo}/>;
    } else {
        return existingLicenseForm
    }
}

export default ExistingLicense;
