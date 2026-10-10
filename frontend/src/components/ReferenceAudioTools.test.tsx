import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { ReferenceAudioTools } from "./ReferenceAudioTools";
import type { JobEvent } from "../types";

const completed = (text:string): JobEvent => ({id:"asr",kind:"transcription",status:"completed",progress:1,stage:"已完成",message:"",speed_bytes_per_second:null,payload:{},result:{text},error:null,created_at:"",updated_at:""});
const props={projectPath:"E:/test",referenceAudio:"Sources/ref.wav",referenceText:"",asrReady:true,onReference:vi.fn(),onText:vi.fn(),onProjectChange:vi.fn(),onError:vi.fn()};
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.clearAllMocks()});

describe("reference audio tools",()=>{
  it("fills recognized text without uploading reference audio to a remote endpoint",async()=>{
    vi.spyOn(api,"transcribe").mockResolvedValue(completed("测试台词"));
    render(<ReferenceAudioTools {...props}/>);
    fireEvent.click(screen.getByRole("button",{name:"识别台词"}));
    await waitFor(()=>expect(props.onText).toHaveBeenCalledWith("测试台词"));
    expect(api.transcribe).toHaveBeenCalledWith("E:/test","Sources/ref.wav");
  });
  it("does not overwrite a transcript edited while recognition is pending",async()=>{
    let resolve!: (value:JobEvent)=>void;
    vi.spyOn(api,"transcribe").mockReturnValue(new Promise(done=>{resolve=done}));
    const {rerender}=render(<ReferenceAudioTools {...props}/>);
    fireEvent.click(screen.getByRole("button",{name:"识别台词"}));
    rerender(<ReferenceAudioTools {...props} referenceText="用户已经修改"/>);
    await act(async()=>resolve(completed("识别内容")));
    expect(props.onText).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button",{name:"使用识别文本"}));
    expect(props.onText).toHaveBeenCalledWith("识别内容");
  });
  it("releases a stream whose permission resolves after leaving the view",async()=>{
    let resolve!: (value:MediaStream)=>void;
    const stop=vi.fn();
    Object.defineProperty(navigator,"mediaDevices",{configurable:true,value:{getUserMedia:vi.fn().mockReturnValue(new Promise(done=>{resolve=done}))}});
    vi.stubGlobal("MediaRecorder",class {});
    const {unmount}=render(<ReferenceAudioTools {...props}/>);
    fireEvent.click(screen.getByRole("button",{name:"麦克风录制"}));
    unmount();
    await act(async()=>resolve({getTracks:()=>[{stop}]} as unknown as MediaStream));
    expect(stop).toHaveBeenCalledTimes(1);
    vi.unstubAllGlobals();
  });
  it("explains microphone permission denial and keeps file recognition available",async()=>{
    Object.defineProperty(navigator,"mediaDevices",{configurable:true,value:{getUserMedia:vi.fn().mockRejectedValue(new DOMException("denied","NotAllowedError"))}});
    vi.stubGlobal("MediaRecorder",class {});
    render(<ReferenceAudioTools {...props}/>);
    fireEvent.click(screen.getByRole("button",{name:"麦克风录制"}));
    await waitFor(()=>expect(props.onError).toHaveBeenCalledWith(expect.stringContaining("麦克风权限未开启")));
    expect(screen.getByRole("button",{name:"识别台词"})).toBeEnabled();
    vi.unstubAllGlobals();
  });
});
