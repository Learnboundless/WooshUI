import { describe,it,expect } from "vitest";
import {automaticSoundName,sfxFamilies} from "./sfx";
import type {GeneratedAsset} from "./types";
const asset=(id:string,kind:GeneratedAsset['kind'],parent:string|null=null):GeneratedAsset=>({id,name:id,kind,parent_asset_id:parent,generation_group_id:'batch',relative_path:id+'.wav',source:'generated',prompt_original:'机械落地',prompt_conditioned:null,model_id:'Woosh-DFlow',seed:1,sample_rate:48000,channel_count:1,duration_seconds:1,stem_role:null,music_metadata:null,favorite:false,tags:[],created_at:'2026-09-12'});
describe('sound families',()=>{
 it('keeps variations and trims together and excludes all non-sound resources',()=>{
   const family=sfxFamilies([asset('original','sfx'),asset('variant','sfx','original'),asset('trim','render','variant'),asset('speech','voice_line'),asset('speech-trim','render','speech'),asset('music','music_mix'),asset('reference','imported')]);
   expect(family).toHaveLength(1);expect(family[0].versions.map(a=>a.id)).toEqual(['original','variant','trim']);
 });
 it('groups siblings after the original is removed',()=>expect(sfxFamilies([asset('b','sfx','a'),asset('c','sfx','a')])).toHaveLength(1));
 it('derives a safe short title from the current prompt',()=>{expect(automaticSoundName('请生成一个重型机甲落地，金属撞击')).toBe('重型机甲落地');expect(automaticSoundName('a heavy mech landing with a metallic impact')).toBe('heavy mech landing')});
});

it('archives legacy variants by explicit filename numbering and close timestamps, without changing assets',()=>{
 const first={...asset('a','sfx'),name:'SFX_generated_01_2',generation_group_id:null,created_at:'2026-07-30T13:15:28Z'};
 const second={...asset('b','sfx'),name:'SFX_generated_02_2',generation_group_id:null,created_at:'2026-07-30T13:15:29Z'};
 const later={...asset('c','sfx'),name:'SFX_generated_01_3',generation_group_id:null,created_at:'2026-07-30T13:20:00Z'};
 const result=sfxFamilies([first,second,later]);expect(result).toHaveLength(2);expect(result[0].inferred).toBe(true);expect(result[0].versions).toHaveLength(2);expect(second.parent_asset_id).toBeNull();
});
